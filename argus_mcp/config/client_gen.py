"""Client configuration generator.

Produces MCP client configs pointing to Argus MCP's own endpoint
for popular editors/clients:

* Claude Desktop (``claude_desktop_config.json``)
* Cursor
* VS Code (``settings.json`` fragment)
* Claude Code (CLI)

Usage::

    from argus_mcp.config.client_gen import generate_client_config

    config_str = generate_client_config("claude-desktop", host="127.0.0.1", port=9000)
"""

from __future__ import annotations

import json
from typing import Any, Dict, Literal

ClientType = Literal["claude-desktop", "cursor", "vscode", "claude-code"]

SUPPORTED_CLIENTS: list[ClientType] = ["claude-desktop", "cursor", "vscode", "claude-code"]


def generate_client_config(
    client: ClientType,
    *,
    host: str = "127.0.0.1",
    port: int = 9000,
    transport: str = "sse",
    server_name: str = "argus-mcp",
) -> str:
    """Return a JSON config string for the given *client* type.

    Parameters
    ----------
    client:
        Target client identifier.
    host / port:
        Argus's listening address.
    transport:
        ``sse`` or ``streamable-http``.
    server_name:
        Display name used in the client config.
    """
    url = _build_url(host, port, transport)
    payload = _GENERATORS[client](url, server_name, transport)
    return json.dumps(payload, indent=2)


def _build_url(host: str, port: int, transport: str) -> str:
    base = f"http://{host}:{port}"
    if transport == "sse":
        return f"{base}/sse"
    return f"{base}/mcp"


def _claude_desktop(url: str, name: str, transport: str) -> Dict[str, Any]:
    return {
        "mcpServers": {
            name: {
                "transport": "sse" if transport == "sse" else "streamable-http",
                "url": url,
            }
        }
    }


def _cursor(url: str, name: str, transport: str) -> Dict[str, Any]:
    return {
        "mcpServers": {
            name: {
                "url": url,
            }
        }
    }


def _vscode(url: str, name: str, transport: str) -> Dict[str, Any]:
    return {
        "mcp": {
            "servers": {
                name: {
                    "type": "sse" if transport == "sse" else "streamable-http",
                    "url": url,
                }
            }
        }
    }


def _claude_code(url: str, name: str, transport: str) -> Dict[str, Any]:
    return {
        "mcpServers": {
            name: {
                "type": "sse" if transport == "sse" else "streamable-http",
                "url": url,
            }
        }
    }


_GENERATORS: Dict[str, Any] = {
    "claude-desktop": _claude_desktop,
    "cursor": _cursor,
    "vscode": _vscode,
    "claude-code": _claude_code,
}
