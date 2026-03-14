"""Data models for the MCP Registry API v0.1.

Defines the client-side data types for the registry API contract
(``ServerEntry``, ``ServerPage``, ``ToolDefinition``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ToolDefinition:
    """Describes a single tool exposed by a registered server."""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ServerEntry:
    """A single server entry in the registry catalog.

    Fields intentionally kept minimal — only what the browser/installer
    needs.  Extra keys from the API response are captured in *extra*.
    """

    name: str
    description: str = ""
    transport: str = "stdio"
    url: str = ""
    command: str = ""
    args: List[str] = field(default_factory=list)
    version: str = ""
    icon_url: str = ""
    categories: List[str] = field(default_factory=list)
    tools: List[ToolDefinition] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ServerEntry:
        """Construct from an API JSON payload (tolerant of missing keys)."""
        tools_raw = data.get("tools") or []
        tools = [
            ToolDefinition(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema") or t.get("input_schema") or {},
            )
            for t in tools_raw
            if isinstance(t, dict)
        ]

        known_keys = {
            "name",
            "description",
            "transport",
            "url",
            "command",
            "args",
            "version",
            "icon_url",
            "categories",
            "tools",
        }
        extra = {k: v for k, v in data.items() if k not in known_keys}

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            transport=data.get("transport", "stdio"),
            url=data.get("url", ""),
            command=data.get("command", ""),
            args=data.get("args") or [],
            version=data.get("version", ""),
            icon_url=data.get("icon_url", ""),
            categories=data.get("categories") or [],
            tools=tools,
            extra=extra,
        )

    def to_backend_config(self) -> Dict[str, Any]:
        """Convert to a backend config dict suitable for Argus."""
        if self.transport == "stdio":
            cfg: Dict[str, Any] = {
                "type": "stdio",
                "command": self.command,
            }
            if self.args:
                cfg["args"] = list(self.args)
            return cfg
        if self.transport in ("sse", "streamable-http"):
            return {
                "type": self.transport,
                "url": self.url,
            }
        # Unknown transport — default to streamable-http if URL present, else stdio
        if self.url:
            return {"type": "streamable-http", "url": self.url}
        return {"type": "stdio", "command": self.command}


@dataclass(frozen=True)
class ServerPage:
    """Paginated response from the registry ``GET /v0/servers`` endpoint."""

    servers: List[ServerEntry]
    next_cursor: Optional[str] = None
    total: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ServerPage:
        """Parse from API JSON."""
        raw_servers = data.get("servers") or data.get("items") or []
        servers = [ServerEntry.from_dict(s) for s in raw_servers if isinstance(s, dict)]
        return cls(
            servers=servers,
            next_cursor=data.get("next_cursor") or data.get("nextCursor"),
            total=data.get("total"),
        )
