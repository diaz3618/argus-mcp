"""Command tree and dynamic API completion refresh."""

from __future__ import annotations

__all__ = ["build_command_tree", "refresh_completions"]

from typing import Any, Final

from argus_cli.client import ArgusClientError
from argus_cli.repl.state import ReplState


def _theme_names() -> list[str]:
    """Return available theme names for completion."""
    from argus_cli.theme import THEME_NAMES

    return THEME_NAMES


# Static portion of the command tree (no dynamic API data).
_STATIC_TREE: Final[dict[str, Any]] = {
    "server": {"start": None, "stop": None, "status": None, "build": None, "clean": None},
    "config": {
        "show": None,
        "validate": None,
        "diff": None,
        "reload": None,
        "export": None,
        "init": None,
        "local": None,
        "themes": None,
    },
    "auth": {"status": None, "configure": None, "test": None},
    "health": {"status": None, "sessions": None, "versions": None, "groups": None},
    "audit": {"list": None, "export": None},
    "events": {"list": None, "stream": None},
    "operations": {"optimizer": None, "telemetry": None},
    "batch": {"reconnect-all": None, "restart-all": None},
    "alias": None,
    "unalias": None,
    "help": None,
    "clear": None,
    "history": None,
    "exit": None,
    "quit": None,
}


def build_command_tree(state: ReplState) -> dict[str, Any]:
    """Build NestedCompleter dict with dynamic API-sourced values."""
    backend_dict = {n: None for n in state.completions.backend_names} or None
    tool_dict = {n: None for n in state.completions.tool_names} or None
    resource_dict = {n: None for n in state.completions.resource_uris} or None
    prompt_dict = {n: None for n in state.completions.prompt_names} or None
    skill_dict = {n: None for n in state.completions.skill_names} or None
    workflow_dict = {n: None for n in state.completions.workflow_names} or None
    secret_dict = {n: None for n in state.completions.secret_names} or None

    dynamic: dict[str, Any] = {
        "backends": {
            "list": None,
            "inspect": backend_dict,
            "reconnect": backend_dict,
            "health": None,
            "groups": None,
            "sessions": None,
            "versions": None,
        },
        "tools": {
            "list": None,
            "inspect": tool_dict,
            "call": tool_dict,
            "rename": tool_dict,
            "filter": None,
        },
        "resources": {"list": None, "read": resource_dict},
        "prompts": {"list": None, "get": prompt_dict},
        "registry": {"search": None, "inspect": None, "install": None},
        "secrets": {
            "list": None,
            "set": secret_dict,
            "get": secret_dict,
            "delete": secret_dict,
        },
        "skills": {
            "list": None,
            "inspect": skill_dict,
            "enable": skill_dict,
            "disable": skill_dict,
            "apply": skill_dict,
        },
        "workflows": {"list": None, "run": workflow_dict, "history": workflow_dict},
        "use": {"backend": backend_dict},
        "watch": None,
        "connect": None,
        "set": {
            "output": {"rich": None, "json": None, "table": None, "text": None},
            "no-color": {"true": None, "false": None},
            "theme": {t: None for t in _theme_names()},
            "show-toolbar": {"true": None, "false": None},
            "vi-mode": {"true": None, "false": None},
        },
    }

    return {**_STATIC_TREE, **dynamic}


def refresh_completions(state: ReplState) -> None:
    """Fetch dynamic values from the API to populate completions and status."""
    from argus_cli.client import ArgusClient

    conn = state.connection
    comp = state.completions

    try:
        with ArgusClient(state.config) as client:
            try:
                data = client.health()
                conn.server_status = data.get("status", "unknown")
                conn.is_connected = True
            except ArgusClientError:
                conn.is_connected = False
                conn.server_status = "disconnected"
                return

            try:
                data = client.status()
                service = data.get("service", {})
                conn.version = service.get("version", "")
                uptime_s = service.get("uptime_seconds", 0)
                if uptime_s:
                    hours, remainder = divmod(int(uptime_s), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    conn.uptime = f"{hours}h{minutes}m{seconds}s"
            except ArgusClientError:
                pass

            try:
                data = client.backends()
                backends = data.get("backends", [])
                comp.backend_names = [b["name"] for b in backends if "name" in b]
                conn.backend_count = len(backends)
                conn.healthy_count = sum(
                    1 for b in backends if b.get("health", {}).get("status") == "healthy"
                )
            except ArgusClientError:
                pass

            try:
                data = client.capabilities()
                comp.tool_names = [t["name"] for t in data.get("tools", []) if "name" in t]
                comp.resource_uris = [r["uri"] for r in data.get("resources", []) if "uri" in r]
                comp.prompt_names = [p["name"] for p in data.get("prompts", []) if "name" in p]
            except ArgusClientError:
                pass

            try:
                data = client.events(limit=1)
                events_list = data.get("events", [])
                conn.last_event_age = "recent" if events_list else "none"
            except ArgusClientError:
                conn.last_event_age = "n/a"

    except ArgusClientError:
        conn.is_connected = False
        conn.server_status = "disconnected"
