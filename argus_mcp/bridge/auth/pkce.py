"""OAuth 2.0 Authorization Code + PKCE (S256) flow.

Implements a browser-based interactive OAuth flow for MCP servers that
require user authentication.  This is the flow used by servers like
Semgrep, GitHub, etc. when they need a user's identity.

Flow overview
-------------
1. Generate a cryptographic code-verifier / code-challenge pair (S256).
2. Start an ephemeral local HTTP server on ``127.0.0.1:<port>`` to
   receive the authorization callback.
3. Launch the user's default browser to the authorization URL.
4. Wait for the callback (authorization code or error).
5. Exchange the authorization code + verifier for an access token.
6. Return the token set (access + optional refresh token).

Security
--------
- PKCE S256 prevents authorization code interception.
- State parameter prevents CSRF.
- Callback server binds only to **localhost**.
- Code verifier is 43–128 chars of URL-safe random bytes per RFC 7636.

Usage::

    flow = PKCEFlow(
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        client_id="my-client",
        scopes=["openid", "profile"],
    )
    tokens = await flow.execute()
    # tokens.access_token, tokens.refresh_token, tokens.expires_in
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import sys
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from argus_mcp.constants import DEFAULT_TOKEN_EXPIRES_IN, STACK_CLOSE_TIMEOUT

logger = logging.getLogger(__name__)

_VERIFIER_LENGTH = 64  # bytes → 86 chars base64url (RFC 7636: 43–128)
_CALLBACK_PATH = "/callback"
_CALLBACK_HOST = "127.0.0.1"
_DEFAULT_PORT = 0  # OS picks ephemeral port
_AUTH_TIMEOUT = 120.0  # seconds to wait for browser callback


def _is_headless() -> bool:
    """Return ``True`` when no graphical browser is likely available.

    Checks for SSH sessions, missing DISPLAY on Linux, and non-TTY stdin.
    """
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return True
    if (
        sys.platform.startswith("linux")
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ):
        return True
    return False


def _present_auth_url(auth_url: str, redirect_uri: str) -> None:
    """Present the OAuth authorization URL with headless-environment support.

    In graphical environments, opens the browser automatically.
    In headless environments (SSH, Docker, CI), prints the URL to
    stderr so the user can copy-paste it into a browser.
    """
    headless = _is_headless()

    if headless:
        print(
            "\n" + "=" * 60,
            "\n  OAUTH AUTHORIZATION REQUIRED",
            "\n" + "=" * 60,
            f"\n  Open this URL in a browser:\n\n    {auth_url}\n",
            f"\n  Callback listening on: {redirect_uri}",
            "\n" + "=" * 60 + "\n",
            file=sys.stderr,
        )
        logger.info(
            "Headless environment detected — browser not opened.\n"
            "  Authorization URL printed to stderr.",
        )
    else:
        logger.info(
            "Opening browser for OAuth authorization…\n  URL: %s\n  Listening on %s for callback.",
            auth_url,
            redirect_uri,
        )
        webbrowser.open(auth_url)


@dataclass
class TokenSet:
    """Result of a successful OAuth token exchange."""

    access_token: str
    token_type: str = "Bearer"
    refresh_token: str = ""
    expires_in: float = float(DEFAULT_TOKEN_EXPIRES_IN)
    scope: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PKCEChallenge:
    """PKCE code-verifier and code-challenge pair."""

    verifier: str
    challenge: str
    method: str = "S256"


def generate_pkce_challenge() -> PKCEChallenge:
    """Generate a PKCE S256 code-verifier / code-challenge pair.

    Follows RFC 7636 §4.1–4.2.
    """
    verifier_bytes = secrets.token_bytes(_VERIFIER_LENGTH)
    verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode("ascii")

    challenge_digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(challenge_digest).rstrip(b"=").decode("ascii")

    return PKCEChallenge(verifier=verifier, challenge=challenge)


def generate_state() -> str:
    """Generate a cryptographic state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback parameters."""

    # Set by the server before handling
    result: Optional[Dict[str, str]] = None
    error: Optional[str] = None
    ready_event: Optional[asyncio.Event] = None
    loop: Optional[asyncio.AbstractEventLoop] = None

    def do_GET(self) -> None:  # noqa: N802
        """Handle the OAuth callback redirect."""
        parsed = urlparse(self.path)
        if parsed.path != _CALLBACK_PATH:
            self.send_error(404)
            return

        params = parse_qs(parsed.query)

        if "error" in params:
            self.__class__.error = params["error"][0]
            desc = params.get("error_description", [""])[0]
            logger.warning(
                "OAuth callback received error: %s — %s",
                self.__class__.error,
                desc,
            )
            self._send_html(
                f"<h2>Authentication Failed</h2>"
                f"<p>{self.__class__.error}: {desc}</p>"
                f"<p>You can close this window.</p>"
            )
        elif "code" in params:
            code = params["code"][0]
            state = params.get("state", [""])[0]
            self.__class__.result = {
                "code": code,
                "state": state,
            }
            logger.info(
                "OAuth callback received authorization code (code=%s…, state=%s…)",
                code[:8] if len(code) > 8 else code,
                state[:8] if len(state) > 8 else state,
            )
            self._send_html(
                "<h2>Authentication Successful</h2>"
                "<p>Authorization code received. Exchanging for token…</p>"
                "<p>You can close this window and return to your terminal.</p>"
            )
        else:
            self.__class__.error = "missing_code"
            logger.warning("OAuth callback received no code or error.")
            self._send_html("<h2>Unexpected Response</h2><p>No authorization code received.</p>")

        # Signal the async waiter
        if self.__class__.loop and self.__class__.ready_event:
            self.__class__.loop.call_soon_threadsafe(self.__class__.ready_event.set)

    def _send_html(self, body: str) -> None:
        """Send an HTML response and auto-close script."""
        html = (
            "<!DOCTYPE html><html><head><title>Argus MCP Auth</title></head>"
            f"<body style='font-family:sans-serif;padding:40px;'>{body}"
            "<script>setTimeout(()=>window.close(),3000)</script>"
            "</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Silence default stderr logging — use our logger instead."""
        logger.debug("OAuth callback: %s", format % args)


class PKCEFlow:
    """Execute an OAuth 2.0 Authorization Code + PKCE flow.

    Parameters
    ----------
    authorization_endpoint:
        The authorization URL to redirect the user to.
    token_endpoint:
        The token exchange URL.
    client_id:
        OAuth client identifier.
    scopes:
        Requested OAuth scopes.
    redirect_port:
        Port for the local callback server (0 = OS picks).
    timeout:
        Maximum seconds to wait for the user to complete auth.
    """

    def __init__(
        self,
        authorization_endpoint: str,
        token_endpoint: str,
        client_id: str,
        *,
        client_secret: str = "",
        scopes: Optional[List[str]] = None,
        redirect_port: int = _DEFAULT_PORT,
        timeout: float = _AUTH_TIMEOUT,
    ) -> None:
        self._auth_endpoint = authorization_endpoint
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes or []
        self._port = redirect_port
        self._timeout = timeout
        # Pre-bound callback server state (populated by bind_callback_server)
        self._server: Optional[HTTPServer] = None
        self._redirect_uri: Optional[str] = None

    def bind_callback_server(self) -> str:
        """Pre-bind the local callback server and return the redirect URI.

        Call this **before** Dynamic Client Registration so the exact
        loopback port is known at registration time.  The returned URI
        includes the ephemeral port assigned by the OS.

        The server is *not* started yet — ``execute()`` will start it
        and reuse the pre-bound socket.

        Returns:
            The full redirect URI, e.g. ``http://127.0.0.1:46293/callback``.
        """
        if self._server is not None:
            assert self._redirect_uri is not None  # noqa: S101
            return self._redirect_uri

        self._server = HTTPServer(
            (_CALLBACK_HOST, self._port),
            _CallbackHandler,
        )
        actual_port = self._server.server_address[1]
        self._redirect_uri = f"http://{_CALLBACK_HOST}:{actual_port}{_CALLBACK_PATH}"
        logger.debug(
            "PKCE callback server pre-bound on %s:%d",
            _CALLBACK_HOST,
            actual_port,
        )
        return self._redirect_uri

    async def execute(self) -> TokenSet:
        """Run the full PKCE flow and return tokens.

        If ``bind_callback_server()`` was called beforehand the
        pre-bound server is reused; otherwise a new one is created
        (backwards-compatible behaviour).

        Raises ``RuntimeError`` if the user does not complete auth
        within the timeout, or the server returns an error.
        """
        pkce = generate_pkce_challenge()
        state = generate_state()

        loop = asyncio.get_running_loop()
        ready = asyncio.Event()

        _CallbackHandler.result = None
        _CallbackHandler.error = None
        _CallbackHandler.ready_event = ready
        _CallbackHandler.loop = loop

        # Reuse pre-bound server or create a new one
        if self._server is not None:
            server = self._server
            redirect_uri = self._redirect_uri
            assert redirect_uri is not None  # noqa: S101
        else:
            server = HTTPServer((_CALLBACK_HOST, self._port), _CallbackHandler)
            actual_port = server.server_address[1]
            redirect_uri = f"http://{_CALLBACK_HOST}:{actual_port}{_CALLBACK_PATH}"

        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            auth_params = {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": pkce.challenge,
                "code_challenge_method": pkce.method,
            }
            if self._scopes:
                auth_params["scope"] = " ".join(self._scopes)

            auth_url = f"{self._auth_endpoint}?{urlencode(auth_params)}"

            # Present auth URL (opens browser or prints to stderr in headless)
            _present_auth_url(auth_url, redirect_uri)

            try:
                await asyncio.wait_for(ready.wait(), timeout=self._timeout)
            except asyncio.CancelledError:
                logger.info("PKCE authorization flow cancelled.")
                raise
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"OAuth authorization timed out after {self._timeout}s. "
                    "Please retry and complete the browser flow."
                ) from None

            if _CallbackHandler.error:
                raise RuntimeError(f"OAuth authorization failed: {_CallbackHandler.error}")

            result = _CallbackHandler.result
            if not result or "code" not in result:
                raise RuntimeError("No authorization code received.")

            if result.get("state") != state:
                raise RuntimeError("OAuth state mismatch — possible CSRF attack.")

            # Exchange code for tokens
            return await self._exchange_code(
                result["code"],
                redirect_uri,
                pkce.verifier,
            )

        finally:
            server.shutdown()
            server_thread.join(timeout=STACK_CLOSE_TIMEOUT)
            # Clear pre-bound state so a fresh server is used on retry
            self._server = None
            self._redirect_uri = None

    async def _exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> TokenSet:
        """Exchange the authorization code for an access token."""
        import httpx  # noqa: PLC0415

        data: Dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self._client_id,
            "code_verifier": code_verifier,
        }
        if self._client_secret:
            data["client_secret"] = self._client_secret

        logger.debug(
            "Token exchange request → [token_endpoint redacted]\n  redirect_uri: %s\n  code: %s…",
            redirect_uri,
            code[:4] + "***" if len(code) > 4 else "***",
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self._token_endpoint,
                data=data,
                headers={"Accept": "application/json"},
            )
            if resp.status_code >= 400:
                # nosemgrep: python-logger-credential-disclosure (logs HTTP status, not token)
                logger.error(
                    "Token exchange failed: HTTP %d",
                    resp.status_code,
                )
            resp.raise_for_status()

        payload = resp.json()
        tokens = TokenSet(
            access_token=payload["access_token"],
            token_type=payload.get("token_type", "Bearer"),
            refresh_token=payload.get("refresh_token", ""),
            expires_in=float(payload.get("expires_in", DEFAULT_TOKEN_EXPIRES_IN)),
            scope=payload.get("scope", ""),
            raw=payload,
        )
        logger.info(
            "OAuth token exchange succeeded (expires_in=%.0fs, refresh=%s).",
            tokens.expires_in,
            bool(tokens.refresh_token),
        )
        return tokens


async def refresh_access_token(
    token_endpoint: str,
    client_id: str,
    refresh_token: str,
    *,
    client_secret: str = "",
    timeout: float = 30.0,
) -> TokenSet:
    """Use a refresh token to obtain a new access token.

    Raises ``httpx.HTTPStatusError`` if the refresh fails
    (e.g. token revoked).
    """
    import httpx  # noqa: PLC0415

    data: Dict[str, str] = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    if client_secret:
        data["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            token_endpoint,
            data=data,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()

    payload = resp.json()
    return TokenSet(
        access_token=payload["access_token"],
        token_type=payload.get("token_type", "Bearer"),
        refresh_token=payload.get("refresh_token", refresh_token),
        expires_in=float(payload.get("expires_in", DEFAULT_TOKEN_EXPIRES_IN)),
        scope=payload.get("scope", ""),
        raw=payload,
    )
