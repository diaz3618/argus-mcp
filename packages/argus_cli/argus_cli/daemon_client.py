"""Async client for the argusd Go daemon over Unix Domain Socket.

Provides a thin wrapper around httpx's UDS transport for communicating
with the argusd API.  All JSON endpoints return ``dict`` payloads;
streaming endpoints (logs, stats, events) yield dicts via
:class:`~collections.abc.AsyncGenerator`.

Usage::

    async with DaemonClient() as client:
        health = await client.health()
        containers = await client.list_containers()
        async for event in client.stream_events():
            print(event)
"""

from __future__ import annotations

__all__ = [
    "DaemonClient",
    "DaemonError",
    "default_socket_path",
]

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────

_BASE_URL = "http://argusd"
_JSON_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_STREAM_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0)


# ── Helpers ────────────────────────────────────────────────────────────


def default_socket_path() -> str:
    """Return the default argusd UDS path, matching the Go daemon logic."""
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return os.path.join(xdg, "argusd.sock")
    return os.path.join(tempfile.gettempdir(), "argusd.sock")


# ── Error ──────────────────────────────────────────────────────────────


class DaemonError(Exception):
    """Error communicating with the argusd daemon."""

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


# ── Client ─────────────────────────────────────────────────────────────


class DaemonClient:
    """Async HTTP client for the argusd Go daemon over UDS.

    Parameters
    ----------
    socket_path:
        Path to the argusd Unix Domain Socket.
        Defaults to :func:`default_socket_path`.
    """

    def __init__(self, socket_path: str | None = None) -> None:
        self._socket_path = socket_path or default_socket_path()
        self._client: httpx.AsyncClient | None = None

    # ── Lifecycle ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create the underlying httpx async client with UDS transport."""
        if self._client is not None:
            return
        transport = httpx.AsyncHTTPTransport(uds=self._socket_path)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url=_BASE_URL,
            timeout=_JSON_TIMEOUT,
        )

    async def close(self) -> None:
        """Shut down the HTTP client gracefully."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    @property
    def is_connected(self) -> bool:
        return self._client is not None and not self._client.is_closed

    @property
    def socket_path(self) -> str:
        return self._socket_path

    @property
    def socket_exists(self) -> bool:
        return Path(self._socket_path).exists()

    # ── Auto-start ─────────────────────────────────────────────────

    @staticmethod
    def find_binary(hint: str | None = None) -> str | None:
        """Locate the argusd binary.

        Search order:
        1. Explicit *hint* path (from config ``argusd.binary``)
        2. ``$PATH`` via :func:`shutil.which`
        3. Well-known build location relative to this repo
        """
        if hint:
            p = Path(hint).expanduser()
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
            return None

        # Check PATH
        found = shutil.which("argusd")
        if found:
            return found

        # Check well-known repo build location
        # daemon_client.py lives in packages/argus_cli/argus_cli/
        repo_root = Path(__file__).resolve().parents[3]
        candidate = repo_root / "packages" / "argusd" / "argusd"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

        return None

    def auto_start(self, binary_hint: str | None = None) -> bool:
        """Attempt to start argusd as a detached background process.

        Returns ``True`` if the daemon was started and the socket appeared
        within a short timeout, ``False`` otherwise.
        """
        binary = self.find_binary(binary_hint)
        if binary is None:
            logger.warning("argusd binary not found — cannot auto-start")
            return False

        logger.info("Auto-starting argusd: %s (socket: %s)", binary, self._socket_path)
        try:
            subprocess.Popen(  # noqa: S603
                [binary, "-socket", self._socket_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            logger.warning("Failed to spawn argusd: %s", exc)
            return False

        # Wait for the socket to appear (up to 3 seconds)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if Path(self._socket_path).exists():
                logger.info("argusd socket appeared at %s", self._socket_path)
                return True
            time.sleep(0.1)

        logger.warning("argusd started but socket did not appear within 3 s")
        return False

    # ── Internal helpers ───────────────────────────────────────────

    def _ensure_connected(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            raise DaemonError("DaemonClient is not connected; call connect() first")
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = self._ensure_connected()
        try:
            resp = await client.request(method, f"/v1{path}", **kwargs)
        except httpx.ConnectError as exc:
            raise DaemonError(
                f"Cannot connect to argusd at {self._socket_path}: {exc}",
            ) from exc
        except httpx.TimeoutException as exc:
            raise DaemonError(f"Timeout communicating with argusd: {exc}") from exc

        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("error", resp.text)
            except (json.JSONDecodeError, ValueError):
                msg = resp.text
            raise DaemonError(msg, status_code=resp.status_code)

        return resp.json()

    async def _stream_sse(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Open an SSE stream and yield parsed events."""
        from httpx_sse import aconnect_sse

        client = self._ensure_connected()
        try:
            async with aconnect_sse(
                client,
                "GET",
                f"/v1{path}",
                timeout=_STREAM_TIMEOUT,
                params=params,
            ) as event_source:
                async for sse in event_source.aiter_sse():
                    if sse.event == "error":
                        try:
                            data = json.loads(sse.data)
                            msg = data.get("error", sse.data)
                        except (json.JSONDecodeError, TypeError):
                            msg = sse.data
                        raise DaemonError(msg)
                    try:
                        data = json.loads(sse.data)
                    except (json.JSONDecodeError, TypeError):
                        data = sse.data
                    yield {"event": sse.event, "data": data}
        except httpx.ConnectError as exc:
            raise DaemonError(
                f"Cannot connect to argusd at {self._socket_path}: {exc}",
            ) from exc

    # ── Health ─────────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """Check daemon health and capability summary."""
        return await self._request("GET", "/health")

    # ── Docker Containers ──────────────────────────────────────────

    async def list_containers(self) -> list[dict[str, Any]]:
        """List all Argus-managed containers."""
        return await self._request("GET", "/containers")  # type: ignore[return-value]

    async def inspect_container(self, container_id: str) -> dict[str, Any]:
        """Return detailed info for a container."""
        return await self._request("GET", f"/containers/{container_id}")

    async def start_container(self, container_id: str) -> dict[str, Any]:
        """Start a container."""
        return await self._request("POST", f"/containers/{container_id}/start")

    async def stop_container(self, container_id: str) -> dict[str, Any]:
        """Stop a container."""
        return await self._request("POST", f"/containers/{container_id}/stop")

    async def restart_container(self, container_id: str) -> dict[str, Any]:
        """Restart a container."""
        return await self._request("POST", f"/containers/{container_id}/restart")

    async def remove_container(self, container_id: str) -> dict[str, Any]:
        """Remove a container."""
        return await self._request("POST", f"/containers/{container_id}/remove")

    async def stream_logs(
        self,
        container_id: str,
        *,
        tail: str | None = None,
        since: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream container logs via SSE.

        Yields dicts with ``event="log"`` and ``data`` containing
        the log line payload.
        """
        params: dict[str, str] = {}
        if tail is not None:
            params["tail"] = tail
        if since is not None:
            params["since"] = since
        async for event in self._stream_sse(
            f"/containers/{container_id}/logs",
            params=params or None,
        ):
            yield event

    async def stream_stats(
        self,
        container_id: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream container resource stats via SSE.

        Yields dicts with ``event="stats"`` and ``data`` containing
        CPU, memory, and network usage.
        """
        async for event in self._stream_sse(f"/containers/{container_id}/stats"):
            yield event

    # ── Docker Events ──────────────────────────────────────────────

    async def stream_events(self) -> AsyncGenerator[dict[str, Any], None]:
        """Stream Docker events for Argus containers via SSE.

        Yields dicts with ``event="docker_event"`` and ``data`` containing
        the event payload.
        """
        async for event in self._stream_sse("/events"):
            yield event

    # ── Kubernetes Pods ────────────────────────────────────────────

    async def list_pods(self) -> list[dict[str, Any]]:
        """List all Argus-managed Kubernetes pods."""
        return await self._request("GET", "/pods")  # type: ignore[return-value]

    async def describe_pod(self, namespace: str, name: str) -> dict[str, Any]:
        """Return detailed info for a Kubernetes pod."""
        return await self._request("GET", f"/pods/{namespace}/{name}")

    async def delete_pod(self, namespace: str, name: str) -> dict[str, Any]:
        """Delete an Argus-managed Kubernetes pod."""
        return await self._request("DELETE", f"/pods/{namespace}/{name}")

    async def stream_pod_logs(
        self,
        namespace: str,
        name: str,
        *,
        container: str | None = None,
        tail: str | None = None,
        since: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream Kubernetes pod logs via SSE.

        Yields dicts with ``event="log"`` and ``data`` containing
        the log line payload.
        """
        params: dict[str, str] = {}
        if container is not None:
            params["container"] = container
        if tail is not None:
            params["tail"] = tail
        if since is not None:
            params["since"] = since
        async for event in self._stream_sse(
            f"/pods/{namespace}/{name}/logs",
            params=params or None,
        ):
            yield event

    async def pod_events(self, namespace: str, name: str) -> list[dict[str, Any]]:
        """Return Kubernetes events for a specific pod."""
        return await self._request("GET", f"/pods/{namespace}/{name}/events")  # type: ignore[return-value]

    # ── Kubernetes Deployments ─────────────────────────────────────

    async def rollout_restart(self, namespace: str, name: str) -> dict[str, Any]:
        """Trigger a rolling restart of a deployment."""
        return await self._request("POST", f"/deployments/{namespace}/{name}/restart")
