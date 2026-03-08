"""Authentication providers for outgoing backend connections.

Implements four strategies:

* **StaticTokenProvider** – fixed headers from config (env var expansion supported).
* **OAuth2Provider** – OAuth 2.0 Client Credentials grant (machine-to-machine).
* **PKCEAuthProvider** – OAuth 2.0 Authorization Code + PKCE (interactive browser flow).
* **create_auth_provider** – factory that builds a provider from a config dict.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Any, Dict, List, Optional

from argus_mcp.bridge.auth.token_cache import TokenCache

logger = logging.getLogger(__name__)


# ── Abstract base ─────────────────────────────────────────────────────


class AuthProvider(abc.ABC):
    """Base class for outgoing-authentication strategies."""

    @abc.abstractmethod
    async def get_headers(self) -> Dict[str, str]:
        """Return HTTP headers to inject into outgoing requests."""

    @abc.abstractmethod
    def redacted_repr(self) -> str:
        """Human-readable description with sensitive values masked."""


# ── Static headers ───────────────────────────────────────────────────


class StaticTokenProvider(AuthProvider):
    """Inject fixed headers into every request.

    Values may contain ``${ENV_VAR}`` references — these must have been
    expanded **before** the provider is constructed (config loader does
    this at load time).
    """

    def __init__(self, headers: Dict[str, str]) -> None:
        self._headers = dict(headers)

    async def get_headers(self) -> Dict[str, str]:
        return dict(self._headers)

    def redacted_repr(self) -> str:
        safe: Dict[str, str] = {}
        for k, v in self._headers.items():
            if any(word in k.lower() for word in ("auth", "token", "key", "secret")):
                safe[k] = _redact(v)
            else:
                safe[k] = v
        return f"StaticTokenProvider(headers={safe})"


# ── OAuth 2.0 Client Credentials ────────────────────────────────────


class OAuth2Provider(AuthProvider):
    """OAuth 2.0 client-credentials grant.

    Acquires a bearer token from *token_url* using *client_id* /
    *client_secret* and caches it until near-expiry.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scopes: Optional[list[str]] = None,
        expiry_buffer: float = 30.0,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes or []
        self._cache = TokenCache(expiry_buffer=expiry_buffer)
        self._lock = asyncio.Lock()

    async def get_headers(self) -> Dict[str, str]:
        token = self._cache.get()
        if token is None:
            async with self._lock:
                # Double-check after acquiring lock
                token = self._cache.get()
                if token is None:
                    token = await self._fetch_token()
        return {"Authorization": f"Bearer {token}"}

    async def _fetch_token(self) -> str:
        """POST to the token endpoint and cache the result."""
        import httpx  # noqa: PLC0415 — lazy import keeps httpx optional

        data: Dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scopes:
            data["scope"] = " ".join(self._scopes)

        # nosemgrep: python-logger-credential-disclosure (logs URL, not credentials)
        logger.debug("OAuth2 token request → %s", self._token_url)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self._token_url, data=data)
            resp.raise_for_status()

        payload: Dict[str, Any] = resp.json()
        access_token: str = payload["access_token"]
        expires_in = float(payload.get("expires_in", 3600))
        self._cache.set(access_token, expires_in)
        logger.info(
            "OAuth2 token acquired (expires_in=%.0fs).",
            expires_in,
        )
        return access_token

    def redacted_repr(self) -> str:
        return (
            f"OAuth2Provider(token_url={self._token_url!r}, "
            f"client_id={self._client_id!r}, "
            f"client_secret={_redact(self._client_secret)})"
        )


# ── OAuth 2.0 Authorization Code + PKCE ─────────────────────────────


class PKCEAuthProvider(AuthProvider):
    """OAuth 2.0 Authorization Code + PKCE (S256) for interactive auth.

    On first call to :meth:`get_headers`, the provider attempts to load
    a cached token from disk.  If none exists (or has expired without a
    usable refresh token), it launches a browser-based PKCE flow.

    Parameters
    ----------
    backend_name:
        The name of the backend this provider is for (used as storage key).
    authorization_endpoint:
        The OAuth authorization URL.
    token_endpoint:
        The OAuth token exchange URL.
    client_id:
        OAuth client identifier.
    client_secret:
        Optional client secret (some providers require it even for public clients).
    scopes:
        Requested OAuth scopes.
    token_dir:
        Override for the persistent token storage directory.
    """

    def __init__(
        self,
        backend_name: str,
        authorization_endpoint: str,
        token_endpoint: str,
        client_id: str,
        *,
        client_secret: str = "",
        scopes: Optional[List[str]] = None,
        token_dir: Optional[str] = None,
    ) -> None:
        self._backend_name = backend_name
        self._auth_endpoint = authorization_endpoint
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes or []
        self._cache = TokenCache(expiry_buffer=60.0)
        self._lock = asyncio.Lock()
        self._token_dir = token_dir

    async def get_headers(self) -> Dict[str, str]:
        """Return an ``Authorization: Bearer …`` header.

        Attempts (in order): in-memory cache → disk store → refresh →
        interactive browser flow.
        """
        # 1. In-memory cache
        token = self._cache.get()
        if token:
            return {"Authorization": f"Bearer {token}"}

        async with self._lock:
            # Double-check after lock
            token = self._cache.get()
            if token:
                return {"Authorization": f"Bearer {token}"}
            token = await self._resolve_token()

        return {"Authorization": f"Bearer {token}"}

    async def _resolve_token(self) -> str:
        """Try disk store, refresh, or interactive flow."""
        from argus_mcp.bridge.auth.pkce import PKCEFlow, refresh_access_token
        from argus_mcp.bridge.auth.store import TokenStore

        store = TokenStore(self._token_dir)

        # 2. Disk store
        stored = await store.load(self._backend_name)
        if stored and stored.access_token:
            self._cache.set(stored.access_token, stored.expires_in)
            logger.info(
                "[%s] Using stored OAuth token.",
                self._backend_name,
            )
            return stored.access_token

        # 3. Refresh (stored has expired access_token but valid refresh)
        if stored and stored.refresh_token:
            try:
                refreshed = await refresh_access_token(
                    self._token_endpoint,
                    self._client_id,
                    stored.refresh_token,
                    client_secret=self._client_secret,
                )
                self._cache.set(refreshed.access_token, refreshed.expires_in)
                await store.save(self._backend_name, refreshed)
                logger.info(
                    "[%s] OAuth token refreshed via refresh_token.",
                    self._backend_name,
                )
                return refreshed.access_token
            except Exception as exc:
                logger.warning(
                    "[%s] Token refresh failed, will re-authenticate: %s",
                    self._backend_name,
                    type(exc).__name__,
                )

        # 4. Interactive PKCE flow (browser)
        logger.info(
            "[%s] No valid token — launching browser OAuth flow…",
            self._backend_name,
        )
        flow = PKCEFlow(
            authorization_endpoint=self._auth_endpoint,
            token_endpoint=self._token_endpoint,
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=self._scopes,
        )
        tokens = await flow.execute()
        self._cache.set(tokens.access_token, tokens.expires_in)
        await store.save(self._backend_name, tokens)
        return tokens.access_token

    def redacted_repr(self) -> str:
        return (
            f"PKCEAuthProvider(backend={self._backend_name!r}, "
            f"auth_endpoint={self._auth_endpoint!r}, "
            f"client_id={self._client_id!r})"
        )


# ── Factory ──────────────────────────────────────────────────────────


def create_auth_provider(
    auth_cfg: Dict[str, Any],
    *,
    backend_name: str = "",
) -> AuthProvider:
    """Build an :class:`AuthProvider` from a config dict.

    Expected shapes::

        {"type": "static", "headers": {"Authorization": "Bearer $TOKEN"}}

        {"type": "oauth2", "token_url": "…", "client_id": "…",
         "client_secret": "…", "scopes": ["read"]}

        {"type": "pkce", "authorization_endpoint": "…",
         "token_endpoint": "…", "client_id": "…",
         "scopes": ["openid"]}

    Raises :class:`ValueError` for unknown types or missing keys.
    """
    auth_type = auth_cfg.get("type", "")
    if auth_type == "static":
        headers = auth_cfg.get("headers")
        if not isinstance(headers, dict) or not headers:
            raise ValueError("Static auth requires non-empty 'headers' dict.")
        return StaticTokenProvider(headers)

    if auth_type == "oauth2":
        for key in ("token_url", "client_id", "client_secret"):
            if not auth_cfg.get(key):
                raise ValueError(f"OAuth2 auth requires '{key}'.")
        return OAuth2Provider(
            token_url=auth_cfg["token_url"],
            client_id=auth_cfg["client_id"],
            client_secret=auth_cfg["client_secret"],
            scopes=auth_cfg.get("scopes", []),
        )

    if auth_type == "pkce":
        for key in ("authorization_endpoint", "token_endpoint", "client_id"):
            if not auth_cfg.get(key):
                raise ValueError(f"PKCE auth requires '{key}'.")
        return PKCEAuthProvider(
            backend_name=backend_name or auth_cfg.get("backend_name", "unknown"),
            authorization_endpoint=auth_cfg["authorization_endpoint"],
            token_endpoint=auth_cfg["token_endpoint"],
            client_id=auth_cfg["client_id"],
            client_secret=auth_cfg.get("client_secret", ""),
            scopes=auth_cfg.get("scopes", []),
            token_dir=auth_cfg.get("token_dir"),
        )

    raise ValueError(f"Unknown auth type: {auth_type!r}")


# ── Helpers ──────────────────────────────────────────────────────────


def _redact(value: str, visible: int = 4) -> str:
    """Mask all but the last *visible* characters."""
    if len(value) <= visible:
        return "****"
    return "*" * (len(value) - visible) + value[-visible:]
