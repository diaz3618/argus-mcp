"""OAuth / OIDC auth discovery and dynamic client registration.

Extracted from :pymod:`argus_mcp.bridge.client_manager` to reduce that
module's complexity.  All functions are free-standing and accept explicit
state so they can be tested in isolation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

from argus_mcp._task_utils import _log_task_exception

if TYPE_CHECKING:
    from argus_mcp.bridge.auth.provider import AuthProvider

logger = logging.getLogger(__name__)


def looks_like_auth_failure(exc: BaseException) -> bool:
    """Return ``True`` if *exc* appears to be an HTTP authentication error.

    Detects HTTP 401/403 status codes inside:
    - ``httpx.HTTPStatusError`` directly.
    - ``ExceptionGroup`` / ``BaseExceptionGroup`` wrapping one or more
      status errors (as produced by the MCP SDK's internal TaskGroup
      when a server returns 401 Unauthorized).
    - String representations mentioning "401" or "Unauthorized" (broad
      fallback for exception types we don't import).
    """

    def _is_auth_status(e: BaseException) -> bool:
        # Check httpx.HTTPStatusError without importing httpx at module
        # level (it's an optional dependency for some backends).
        type_name = type(e).__name__
        if type_name == "HTTPStatusError":
            status = getattr(getattr(e, "response", None), "status_code", 0)
            return status in (401, 403)
        # Broad text check for wrapped error messages
        msg = str(e).lower()
        return "401" in msg or "unauthorized" in msg or "403" in msg

    if _is_auth_status(exc):
        return True

    # Check sub-exceptions inside ExceptionGroup / BaseExceptionGroup
    sub_exceptions = getattr(exc, "exceptions", None)
    if sub_exceptions:
        return any(_is_auth_status(sub) for sub in sub_exceptions)

    return False


async def resolve_auth_headers(
    svr_name: str,
    svr_conf: Dict[str, Any],
    discovered_auth: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, str]]:
    """Resolve outgoing-auth headers for a backend, if configured.

    Checks (in order):
    1. Explicit ``auth`` block in the backend config.
    2. Runtime-discovered auth config from *discovered_auth*.
    """
    auth_cfg = svr_conf.get("auth")
    if not auth_cfg:
        auth_cfg = discovered_auth.get(svr_name)
    if not auth_cfg:
        return None
    try:
        from argus_mcp.bridge.auth.provider import create_auth_provider

        provider = create_auth_provider(auth_cfg, backend_name=svr_name)
        headers = await provider.get_headers()
        logger.info("[%s] Auth provider resolved: %s", svr_name, provider.redacted_repr())
        return headers
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s] Failed to resolve auth headers: %s", svr_name, exc)
        return None


async def resolve_auth_provider(
    svr_name: str,
    svr_conf: Dict[str, Any],
    discovered_auth: Dict[str, Dict[str, Any]],
) -> Optional["AuthProvider"]:
    """Return a long-lived :class:`AuthProvider` for a backend.

    Unlike :func:`resolve_auth_headers` (which creates a throw-away
    provider), this keeps the provider alive so it can be wrapped in
    :class:`McpBearerAuth` for transparent per-request auth + 401 retry.
    """
    auth_cfg = svr_conf.get("auth")
    if not auth_cfg:
        auth_cfg = discovered_auth.get(svr_name)
    if not auth_cfg:
        return None
    try:
        from argus_mcp.bridge.auth.provider import create_auth_provider

        provider = create_auth_provider(auth_cfg, backend_name=svr_name)
        logger.info("[%s] Auth provider created: %s", svr_name, provider.redacted_repr())
        return provider
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s] Failed to create auth provider: %s", svr_name, exc)
        return None


async def attempt_auth_discovery(
    svr_name: str,
    svr_conf: Dict[str, Any],
    svr_type: Optional[str],
    default_reason: str,
    auth_discovery_tasks: Dict[str, asyncio.Task[Any]],
    discovered_auth: Dict[str, Dict[str, Any]],
    progress_cb: Optional[Callable[..., None]] = None,
) -> str:
    """Start OAuth auto-discovery for a backend in the background.

    Returns an updated failure reason string.  Uses task tracking to
    prevent duplicate DCR registrations and PKCE flows — if an auth
    discovery task is already running for this backend, returns
    immediately and lets the retry loop wait on it.

    The background task runs the full PKCE browser flow (up to 600 s).
    The startup coordinator's ``await_auth_discoveries`` waits for it
    with a generous timeout before launching retries.

    For remote backends (SSE / streamable-http) only.
    """
    if svr_type not in ("sse", "streamable-http"):
        return default_reason

    existing_task = auth_discovery_tasks.get(svr_name)
    if existing_task is not None and not existing_task.done():
        logger.info(
            "[%s] Auth discovery already in progress — "
            "retry loop will wait for it before retrying.",
            svr_name,
        )
        return "Auth discovery already running — will retry after browser authentication completes."

    # The PKCE browser flow can take minutes while the user
    # interacts with the authorization page.  We launch it as a
    # background task so the concurrency semaphore is released
    # immediately and other backends can proceed.  The startup
    # coordinator's retry loop (await_auth_discoveries) will wait
    # for this task with a generous timeout before retrying.
    coro = try_auth_discovery(svr_name, svr_conf, discovered_auth, progress_cb)
    task = asyncio.create_task(
        coro,
        name=f"auth_discovery_{svr_name}",
    )
    task.add_done_callback(_log_task_exception)
    auth_discovery_tasks[svr_name] = task

    logger.info(
        "[%s] Auth discovery started in background (PKCE browser flow). "
        "Retry loop will wait for completion.",
        svr_name,
    )
    return "Auth required — PKCE browser flow started. Will retry after authentication completes."


async def try_auth_discovery(
    svr_name: str,
    svr_conf: Dict[str, Any],
    discovered_auth: Dict[str, Dict[str, Any]],
    progress_cb: Optional[Callable[..., None]] = None,
) -> bool:
    """Attempt OAuth auto-discovery for a backend that failed with auth errors.

    Probes the backend URL for RFC 9728 / OIDC metadata.  If the
    server advertises OAuth with PKCE support, runs the interactive
    browser flow and stores the resulting auth config for subsequent
    retry attempts.

    Returns ``True`` if auth was successfully discovered and tokens
    obtained, ``False`` otherwise.
    """
    backend_url = svr_conf.get("url")
    if not backend_url:
        return False

    if svr_conf.get("auth"):
        return False

    if svr_name in discovered_auth:
        return False

    try:
        from argus_mcp.bridge.auth.discovery import discover_oauth_metadata

        logger.info(
            "[%s] Attempting OAuth auto-discovery on %s…",
            svr_name,
            backend_url,
        )

        if progress_cb is not None:
            progress_cb(
                svr_name,
                "initializing",
                "Discovering auth requirements…",
            )

        meta = await discover_oauth_metadata(backend_url, timeout=15.0)
        if not meta:
            logger.info(
                "[%s] No OAuth metadata found — auth discovery failed.",
                svr_name,
            )
            return False

        logger.info(
            "[%s] OAuth discovered: issuer=%s, pkce=%s, registration=%s",
            svr_name,
            meta.issuer,
            meta.supports_pkce,
            meta.supports_dynamic_registration,
        )

        if not meta.authorization_endpoint or not meta.token_endpoint:
            logger.warning(
                "[%s] OAuth metadata incomplete — missing endpoints.",
                svr_name,
            )
            return False

        from argus_mcp.bridge.auth.pkce import PKCEFlow

        scopes = meta.scopes_supported or []
        flow = PKCEFlow(
            authorization_endpoint=meta.authorization_endpoint,
            token_endpoint=meta.token_endpoint,
            client_id="pending",
            scopes=scopes,
            timeout=600.0,
        )

        redirect_uri = flow.bind_callback_server()
        logger.info(
            "[%s] PKCE callback server pre-bound: %s",
            svr_name,
            redirect_uri,
        )

        client_id = ""
        client_secret = ""

        if meta.supports_dynamic_registration:
            try:
                client_id, client_secret = await dynamic_register(
                    svr_name,
                    meta.registration_endpoint,
                    backend_url,
                    redirect_uri=redirect_uri,
                )
            except (OSError, ConnectionError) as exc:
                logger.warning(
                    "[%s] Dynamic client registration failed: %s. Trying without registration.",
                    svr_name,
                    exc,
                )

        if not client_id:
            logger.warning(
                "[%s] No client_id available (registration failed or "
                "not supported). Cannot proceed with PKCE auth.",
                svr_name,
            )
            return False

        flow._client_id = client_id  # noqa: SLF001
        flow._client_secret = client_secret  # noqa: SLF001

        if progress_cb is not None:
            progress_cb(
                svr_name,
                "initializing",
                "Waiting for browser authentication…",
            )

        tokens = await flow.execute()

        from argus_mcp.bridge.auth.store import TokenStore

        store = TokenStore()
        await store.save(svr_name, tokens)

        discovered_auth[svr_name] = {
            "type": "pkce",
            "authorization_endpoint": meta.authorization_endpoint,
            "token_endpoint": meta.token_endpoint,
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": scopes,
        }

        logger.info(
            "[%s] OAuth PKCE auth succeeded — token stored for retry.",
            svr_name,
        )
        if progress_cb is not None:
            progress_cb(
                svr_name,
                "initializing",
                "Authentication successful\u2026",
            )
        return True

    except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
        logger.warning(
            "[%s] Auth discovery/PKCE flow failed: %s",
            svr_name,
            exc,
        )
        return False


async def dynamic_register(
    svr_name: str,
    registration_endpoint: str,
    backend_url: str,
    redirect_uri: str = "",
) -> Tuple[str, str]:
    """Register a dynamic OAuth client (RFC 7591).

    Parameters
    ----------
    redirect_uri:
        The full redirect URI including the ephemeral port, e.g.
        ``http://127.0.0.1:46293/callback``.  When supplied, this
        exact URI is registered so it matches the PKCE callback
        server that is already listening.  If empty, falls back to
        ``http://127.0.0.1/callback`` (legacy behaviour).

    Returns ``(client_id, client_secret)``.
    Raises on failure.
    """
    import httpx  # noqa: PLC0415

    if not redirect_uri:
        redirect_uri = "http://127.0.0.1/callback"

    reg_data = {
        "client_name": f"Argus MCP ({svr_name})",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "application_type": "native",
        "scope": "openid email profile offline_access",
    }

    logger.info(
        "[%s] Dynamic client registration → %s (redirect_uris=%s)",
        svr_name,
        registration_endpoint,
        reg_data["redirect_uris"],
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            registration_endpoint,
            json=reg_data,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

    payload = resp.json()
    client_id = payload.get("client_id", "")
    client_secret = payload.get("client_secret", "")
    registered_uris = payload.get("redirect_uris", [])
    logger.info(
        "[%s] Dynamic registration succeeded: client_id=%s, registered_redirect_uris=%s",
        svr_name,
        client_id[:12] + "…" if len(client_id) > 12 else client_id,
        registered_uris,
    )
    return client_id, client_secret
