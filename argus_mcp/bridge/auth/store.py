"""Persistent token storage for OAuth flows.

Stores OAuth tokens (access + refresh) on disk so that browser-based
authentication does not need to be repeated on every server restart.

Tokens are stored as JSON files under a configurable directory
(defaults to ``~/.config/argus-mcp/tokens/``).  File permissions are
set to ``0600`` (owner-only read/write) to limit exposure.

Each backend gets its own token file, keyed by a sanitised version of
the backend name.

Usage::

    store = TokenStore()
    store.save("semgrep", tokens)
    loaded = store.load("semgrep")
    if loaded:
        print(loaded.access_token)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from argus_mcp.bridge.auth.pkce import TokenSet

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────

_DEFAULT_TOKEN_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "argus-mcp",
    "tokens",
)


# ── Token store ──────────────────────────────────────────────────────────


class TokenStore:
    """File-based persistent token storage.

    Parameters
    ----------
    token_dir:
        Directory to store token files.  Created automatically if it
        does not exist.  Defaults to ``~/.config/argus-mcp/tokens/``.
    """

    def __init__(self, token_dir: Optional[str] = None) -> None:
        self._dir = Path(token_dir or _DEFAULT_TOKEN_DIR)
        self._ensure_dir()

    async def save(self, backend_name: str, tokens: TokenSet) -> None:
        """Persist *tokens* for *backend_name*."""
        path = self._path_for(backend_name)
        data = {
            "access_token": tokens.access_token,
            "token_type": tokens.token_type,
            "refresh_token": tokens.refresh_token,
            "expires_in": tokens.expires_in,
            "scope": tokens.scope,
            "saved_at": time.time(),
        }
        try:
            content = json.dumps(data, indent=2)
            await asyncio.to_thread(path.write_text, content, "utf-8")
            # Restrict permissions — owner-only read/write
            os.chmod(path, 0o600)
            # nosemgrep: python-logger-credential-disclosure (logs name, not value)
            logger.debug(
                "Token saved for backend '%s'",
                backend_name,
            )
        except OSError as exc:
            # nosemgrep: python-logger-credential-disclosure (logs OS error, not token)
            logger.warning(
                "Failed to save token for '%s': %s",
                backend_name,
                exc,
            )

    async def load(self, backend_name: str) -> Optional[TokenSet]:
        """Load stored tokens for *backend_name*.

        Returns ``None`` if no token file exists or the access token
        has expired (based on ``saved_at`` + ``expires_in``).
        """
        path = self._path_for(backend_name)
        if not path.exists():
            return None

        try:
            raw = await asyncio.to_thread(path.read_text, "utf-8")
            data = json.loads(raw)
        except OSError as exc:
            logger.warning(
                "Failed to read token for '%s': %s",
                backend_name,
                exc,
            )
        except json.JSONDecodeError:
            # nosemgrep: python-logger-credential-disclosure
            # Log only the exception type — the message may contain
            # raw file content (token fragments).
            logger.warning(
                "Failed to parse token file for '%s' (corrupt JSON)",
                backend_name,
            )
            return None

        # Check expiry (with 60s buffer)
        saved_at = data.get("saved_at", 0)
        expires_in = data.get("expires_in", 0)
        if saved_at and expires_in:
            elapsed = time.time() - saved_at
            if elapsed >= (expires_in - 60):
                # nosemgrep: python-logger-credential-disclosure (logs elapsed time, not token)
                logger.debug(
                    "Stored access token for '%s' has expired (elapsed=%.0fs).",
                    backend_name,
                    elapsed,
                )
                # Token expired — but there might be a refresh token
                refresh = data.get("refresh_token", "")
                if refresh:
                    return TokenSet(
                        access_token="",  # Mark as expired
                        token_type=data.get("token_type", "Bearer"),
                        refresh_token=refresh,
                        expires_in=0,
                        scope=data.get("scope", ""),
                    )
                return None

        return TokenSet(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            refresh_token=data.get("refresh_token", ""),
            expires_in=data.get("expires_in", 3600),
            scope=data.get("scope", ""),
        )

    def delete(self, backend_name: str) -> bool:
        """Delete the stored token for *backend_name*.

        Returns ``True`` if a file was deleted.
        """
        path = self._path_for(backend_name)
        if path.exists():
            path.unlink()
            # nosemgrep: python-logger-credential-disclosure (logs name, not value)
            logger.debug("Token deleted for backend '%s'.", backend_name)
            return True
        return False

    def list_backends(self) -> list[str]:
        """List backend names that have stored tokens."""
        if not self._dir.exists():
            return []
        return [p.stem for p in self._dir.glob("*.json") if p.is_file()]

    # ── Internal ─────────────────────────────────────────────────────

    def _path_for(self, backend_name: str) -> Path:
        """Get the token file path for a backend name."""
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", backend_name)
        return self._dir / f"{safe_name}.json"

    def _ensure_dir(self) -> None:
        """Create the token directory with restricted permissions."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self._dir, 0o700)
        except OSError as exc:
            # nosemgrep: python-logger-credential-disclosure (logs path, not token)
            logger.warning("Failed to create token directory %s: %s", self._dir, exc)
