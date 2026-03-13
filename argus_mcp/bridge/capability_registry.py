"""MCP capability discovery, registration, and routing."""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple, Type, Union, cast

from mcp import ClientSession
from mcp import types as mcp_types
from mcp.shared.exceptions import McpError

from argus_mcp.bridge.conflict import (
    ConflictAction,
    ConflictStrategy,
    FirstWinsStrategy,
)
from argus_mcp.bridge.filter import CapabilityFilter
from argus_mcp.bridge.rename import RenameMap
from argus_mcp.constants import CAP_FETCH_TIMEOUT

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Discovers, registers, and routes MCP capabilities from backend servers."""

    def __init__(
        self,
        conflict_strategy: Optional[ConflictStrategy] = None,
        filters: Optional[Dict[str, Dict[str, CapabilityFilter]]] = None,
        rename_maps: Optional[Dict[str, RenameMap]] = None,
        cap_fetch_timeouts: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Args:
            conflict_strategy: Strategy for resolving name collisions.
            filters: Per-server, per-capability-type filters.
                Structure: ``{server_name: {cap_type: CapabilityFilter}}``.
            rename_maps: Per-server rename maps.
                Structure: ``{server_name: RenameMap}``.
            cap_fetch_timeouts: Per-server capability fetch timeouts.
                Structure: ``{server_name: timeout_seconds}``.
        """
        self._tools: List[mcp_types.Tool] = []
        self._resources: List[mcp_types.Resource] = []
        self._prompts: List[mcp_types.Prompt] = []
        self._route_map: Dict[str, Tuple[str, str]] = {}
        self._strategy = conflict_strategy or FirstWinsStrategy()
        self._filters = filters or {}
        self._rename_maps = rename_maps or {}
        self._cap_fetch_timeouts = cap_fetch_timeouts or {}
        logger.info(
            "CapabilityRegistry initialized (conflict strategy: %s, "
            "filters for %d server(s), renames for %d server(s)).",
            type(self._strategy).__name__,
            len(self._filters),
            len(self._rename_maps),
        )

    def _parse_list_result(
        self,
        svr_name: str,
        list_method_name: str,
        cap_type: str,
        list_result: Any,
    ) -> List[Any]:
        """Extract capability items from a list method response."""
        if hasattr(list_result, cap_type) and isinstance(getattr(list_result, cap_type), list):
            items: List[Any] = getattr(list_result, cap_type)
            return items
        if isinstance(list_result, list):
            return list_result
        if list_result is None:
            logger.info(
                "[%s] %s() returned None, treating as no %s.",
                svr_name,
                list_method_name,
                cap_type,
            )
            return []
        logger.warning(
            "[%s] %s() returned unknown type %s; unable to parse %s list. Raw value: %r",
            svr_name,
            list_method_name,
            type(list_result),
            cap_type,
            list_result,
        )
        return []

    def _apply_filter_and_rename(
        self,
        svr_name: str,
        cap_type: str,
        cap_item: Union[mcp_types.Tool, mcp_types.Resource, mcp_types.Prompt],
    ) -> Optional[tuple[str, Union[mcp_types.Tool, mcp_types.Resource, mcp_types.Prompt]]]:
        """Apply filter and rename rules. Returns (orig_name, updated_item) or None if filtered."""
        # Apply per-server filter (deny > allow > pass-through).
        svr_filters = self._filters.get(svr_name, {})
        cap_filter = svr_filters.get(cap_type)
        if cap_filter and not cap_filter.is_allowed(cap_item.name):
            logger.debug(
                "[%s] %s '%s' filtered out by deny/allow rules.",
                svr_name,
                cap_type[:-1],
                cap_item.name,
            )
            return None

        # Apply per-server rename / description override (tools only).
        orig_name = cap_item.name
        rename_map = self._rename_maps.get(svr_name)
        if rename_map and cap_type == "tools":
            new_name = rename_map.get_new_name(cap_item.name)
            desc_override = rename_map.get_description_override(cap_item.name)
            updates: Dict[str, Any] = {}
            if new_name != cap_item.name:
                updates["name"] = new_name
                logger.debug("[%s] Renamed tool '%s' -> '%s'.", svr_name, cap_item.name, new_name)
            if desc_override is not None:
                updates["description"] = desc_override
            if updates:
                cap_item = cap_item.model_copy(update=updates)

        return orig_name, cap_item

    def _resolve_conflict(
        self,
        svr_name: str,
        cap_type: str,
        exp_cap_name: str,
        agg_list: List[Any],
    ) -> Optional[str]:
        """Handle name collision. Returns final exposed name, or None to skip."""
        if exp_cap_name not in self._route_map:
            return exp_cap_name

        exist_svr_name, _ = self._route_map[exp_cap_name]
        if exist_svr_name == svr_name:
            logger.warning(
                "[%s] Duplicate %s provided multiple times: '%s'. Only the first instance is registered.",
                svr_name,
                cap_type[:-1],
                exp_cap_name,
            )
            return None

        action = self._strategy.handle_conflict(exp_cap_name, exist_svr_name, svr_name)

        if action.action == ConflictAction.SKIP:
            return None
        if action.action == ConflictAction.REPLACE:
            agg_list[:] = [item for item in agg_list if getattr(item, "name", None) != exp_cap_name]
            del self._route_map[exp_cap_name]
            return exp_cap_name
        if action.action == ConflictAction.RENAME:
            new_name = action.new_name
            if new_name in self._route_map:
                logger.warning(
                    "[%s] Renamed name '%s' also conflicts; skipping.", svr_name, new_name
                )
                return None
            return new_name
        # ConflictAction.ERROR — strategy already raised; fallback.
        return None

    async def _discover_caps_by_type(
        self,
        svr_name: str,
        session: ClientSession,
        cap_type: str,
        list_method_name: str,
        mcp_cls: Union[Type[mcp_types.Tool], Type[mcp_types.Resource], Type[mcp_types.Prompt]],
        agg_list: List[Any],
    ) -> None:
        """
        Generic helper to discover and register a specific capability type.

        Applies the configured conflict resolution strategy when name
        collisions occur between different backend servers.
        """
        logger.debug("[%s] Starting discovery for %s...", svr_name, cap_type)
        try:
            list_method = getattr(session, list_method_name)
            timeout = self._cap_fetch_timeouts.get(svr_name, CAP_FETCH_TIMEOUT)
            logger.debug("[%s] Requesting %s list (timeout %ss)...", svr_name, cap_type, timeout)

            list_result = await asyncio.wait_for(list_method(), timeout=timeout)
            orig_caps = self._parse_list_result(svr_name, list_method_name, cap_type, list_result)
            logger.debug("[%s] Parsed %s raw %s from response.", svr_name, len(orig_caps), cap_type)

            registered_count = 0
            for cap_item_raw in orig_caps:
                if not isinstance(cap_item_raw, mcp_cls):
                    logger.warning(
                        "[%s] Found non-%s object, skipped: %r",
                        svr_name,
                        mcp_cls.__name__,
                        cap_item_raw,
                    )
                    continue

                cap_item = cast(
                    Union[mcp_types.Tool, mcp_types.Resource, mcp_types.Prompt], cap_item_raw
                )
                if not cap_item.name:
                    logger.warning(
                        "[%s] Found unnamed %s, skipped: %r", svr_name, cap_type[:-1], cap_item
                    )
                    continue

                result = self._apply_filter_and_rename(svr_name, cap_type, cap_item)
                if result is None:
                    continue
                orig_name, cap_item = result

                exp_cap_name = self._strategy.transform_name(svr_name, cap_item.name)
                resolved_name = self._resolve_conflict(svr_name, cap_type, exp_cap_name, agg_list)
                if resolved_name is None:
                    continue

                if resolved_name != cap_item.name:
                    cap_item = cap_item.model_copy(update={"name": resolved_name})

                agg_list.append(cap_item)
                self._route_map[resolved_name] = (svr_name, orig_name)
                registered_count += 1

            if registered_count > 0:
                logger.info("[%s] Registered %s unique %s.", svr_name, registered_count, cap_type)
            else:
                logger.info("[%s] No new %s discovered or registered.", svr_name, cap_type)

        except asyncio.TimeoutError:
            logger.error(
                "[%s] %s() timed out (>%ss).", svr_name, list_method_name, CAP_FETCH_TIMEOUT
            )
        except McpError as mcp_e:
            logger.error(
                "[%s] MCP error during %s(): Code=%s, Msg='%s'",
                svr_name,
                list_method_name,
                mcp_e.error.code,
                mcp_e.error.message,
                exc_info=False,
            )
        except Exception:  # noqa: BLE001
            logger.exception("[%s] Unknown error while discovering %s.", svr_name, cap_type)

    async def discover_and_register(self, sessions: Dict[str, ClientSession]) -> None:
        """Discover and register MCP capabilities from active backend sessions."""
        logger.info(
            "Starting capability discovery/registration from %s active sessions...",
            len(sessions),
        )

        self._tools.clear()
        self._resources.clear()
        self._prompts.clear()
        self._route_map.clear()

        discover_tasks = []
        for svr_name, session in sessions.items():
            if not session:
                logger.warning(
                    "Skipping server '%s' because it has no valid session.",
                    svr_name,
                )
                continue

            discover_tasks.append(
                self._discover_caps_by_type(
                    svr_name,
                    session,
                    "tools",
                    "list_tools",
                    mcp_types.Tool,
                    self._tools,
                )
            )
            discover_tasks.append(
                self._discover_caps_by_type(
                    svr_name,
                    session,
                    "resources",
                    "list_resources",
                    mcp_types.Resource,
                    self._resources,
                )
            )
            discover_tasks.append(
                self._discover_caps_by_type(
                    svr_name,
                    session,
                    "prompts",
                    "list_prompts",
                    mcp_types.Prompt,
                    self._prompts,
                )
            )

        results = await asyncio.gather(*discover_tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Capability discovery task %d failed: %s",
                    i,
                    result,
                    exc_info=result,
                )

        logger.info("Capability discovery attempts completed for all backend servers.")
        logger.info(
            "Aggregated discovery: %s tools, %s resources, %s prompts.",
            len(self._tools),
            len(self._resources),
            len(self._prompts),
        )
        logger.debug("Current route map: %s", self._route_map)

    def get_aggregated_tools(self) -> List[mcp_types.Tool]:
        """Get the aggregated tool list."""
        return self._tools.copy()

    def get_aggregated_resources(self) -> List[mcp_types.Resource]:
        """Get the aggregated resource list."""
        return self._resources.copy()

    def get_aggregated_prompts(self) -> List[mcp_types.Prompt]:
        """Get the aggregated prompt list."""
        return self._prompts.copy()

    def get_route_map(self) -> Dict[str, Tuple[str, str]]:
        """Get the capability-to-server routing map."""
        return self._route_map.copy()

    def resolve_capability(self, exp_cap_name: str) -> Optional[Tuple[str, str]]:
        """
        Resolve an exposed capability name to:
        (backend server name, original backend capability name), or None.
        """
        return self._route_map.get(exp_cap_name)

    def remove_backend(self, svr_name: str) -> int:
        """Remove all capabilities belonging to *svr_name*.

        Returns the number of capabilities removed.
        """
        keys_to_remove = [k for k, (s, _) in self._route_map.items() if s == svr_name]
        for key in keys_to_remove:
            del self._route_map[key]

        before_tools = len(self._tools)
        before_resources = len(self._resources)
        before_prompts = len(self._prompts)

        self._tools = [t for t in self._tools if t.name not in keys_to_remove]
        self._resources = [
            r
            for r in self._resources
            if getattr(r, "name", getattr(r, "uri", None)) not in keys_to_remove
        ]
        self._prompts = [p for p in self._prompts if p.name not in keys_to_remove]

        removed = (
            (before_tools - len(self._tools))
            + (before_resources - len(self._resources))
            + (before_prompts - len(self._prompts))
        )
        if removed:
            logger.info("[%s] Removed %d capabilities from registry.", svr_name, removed)
        return removed

    async def discover_single_backend(self, svr_name: str, session: ClientSession) -> None:
        """Re-discover and register capabilities for a single backend.

        Used by the health checker when a backend transitions from
        unhealthy back to healthy.
        """
        logger.info("[%s] Re-discovering capabilities...", svr_name)
        await self._discover_caps_by_type(
            svr_name,
            session,
            "tools",
            "list_tools",
            mcp_types.Tool,
            self._tools,
        )
        await self._discover_caps_by_type(
            svr_name,
            session,
            "resources",
            "list_resources",
            mcp_types.Resource,
            self._resources,
        )
        await self._discover_caps_by_type(
            svr_name,
            session,
            "prompts",
            "list_prompts",
            mcp_types.Prompt,
            self._prompts,
        )
        logger.info(
            "[%s] Re-discovery complete: %d tools, %d resources, %d prompts total.",
            svr_name,
            len(self._tools),
            len(self._resources),
            len(self._prompts),
        )
