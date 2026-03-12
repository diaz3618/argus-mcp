"""ClamAV plugin — antivirus scanning via clamd TCP daemon.

Streams content to a running ``clamd`` daemon for malware detection.
Supports both TCP and Unix-socket connections.

Settings (in ``config.settings``):
    host:           clamd TCP host (default ``127.0.0.1``)
    port:           clamd TCP port (default ``3310``)
    unix_socket:    Unix socket path (overrides host/port when set)
    timeout:        Socket timeout in seconds (default ``30``)
    max_scan_bytes: Max bytes to send for scanning (default ``10485760`` = 10 MB)
    block:          Block when malware is found (default ``True``)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)

_INSTREAM_CMD = b"zINSTREAM\0"
_MAX_CHUNK = 8192


class ClamAVPlugin(PluginBase):
    """Antivirus scanning via clamd daemon."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._host: str = config.settings.get("host", "127.0.0.1")
        self._port: int = int(config.settings.get("port", 3310))
        self._unix_socket: Optional[str] = config.settings.get("unix_socket")
        self._timeout: float = float(config.settings.get("timeout", 30))
        self._max_scan_bytes: int = int(config.settings.get("max_scan_bytes", 10_485_760))
        self._block: bool = config.settings.get("block", True)

    async def resource_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        content = self._extract_content(ctx.arguments)
        if content:
            await self._scan(ctx, content, "resource_pre_fetch")
        return ctx

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        content = self._extract_content_from_result(ctx.result)
        if content:
            await self._scan(ctx, content, "tool_post_invoke")
        return ctx

    async def _scan(
        self,
        ctx: PluginContext,
        data: bytes,
        phase: str,
    ) -> None:
        data = data[: self._max_scan_bytes]
        result = await self._clamd_instream(data)
        if result is None:
            logger.warning("ClamAV: daemon unreachable, skipping scan.")
            return

        if result.startswith("stream: ") and "FOUND" in result:
            virus_name = result.split("stream: ", 1)[-1].replace(" FOUND", "")
            ctx.metadata[f"clamav_{phase}"] = virus_name
            if self._block:
                raise ValueError(f"ClamAV: malware detected — {virus_name}")
            logger.warning("ClamAV: malware detected — %s (permissive mode)", virus_name)

    async def _clamd_instream(self, data: bytes) -> Optional[str]:
        try:
            reader: asyncio.StreamReader
            writer: asyncio.StreamWriter
            if self._unix_socket:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(self._unix_socket),
                    timeout=self._timeout,
                )
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=self._timeout,
                )

            try:
                writer.write(_INSTREAM_CMD)
                offset = 0
                while offset < len(data):
                    chunk = data[offset : offset + _MAX_CHUNK]
                    writer.write(len(chunk).to_bytes(4, "big") + chunk)
                    offset += _MAX_CHUNK
                writer.write(b"\x00\x00\x00\x00")
                await writer.drain()

                response = await asyncio.wait_for(reader.read(4096), timeout=self._timeout)
                return response.decode("utf-8", errors="replace").strip("\x00\n\r ")
            finally:
                writer.close()
                await writer.wait_closed()
        except Exception:
            logger.debug("ClamAV: connection failed.", exc_info=True)
            return None

    @staticmethod
    def _extract_content(arguments: dict[str, Any]) -> Optional[bytes]:
        for key in ("content", "data", "body", "payload"):
            val = arguments.get(key)
            if isinstance(val, bytes):
                return val
            if isinstance(val, str) and val:
                return val.encode("utf-8")
        return None

    @staticmethod
    def _extract_content_from_result(result: Any) -> Optional[bytes]:
        if isinstance(result, bytes):
            return result
        if isinstance(result, str) and len(result) > 0:
            return result.encode("utf-8")
        return None
