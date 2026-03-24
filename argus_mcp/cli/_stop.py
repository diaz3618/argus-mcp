"""Stop and status subcommands for ``argus-mcp``."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from typing import Optional

from argus_mcp.cli._common import _PID_FILE


def _cleanup_pid_file() -> None:
    """Remove the legacy PID file, ignoring missing files."""
    try:
        os.unlink(_PID_FILE)
    except FileNotFoundError:
        pass


def _stop_named_session(session_name: str) -> None:
    """Stop a specific named session by *session_name*."""
    from argus_mcp.sessions import load_session, remove_session, stop_session

    info = load_session(session_name)
    if info is None:
        print(f"No session named '{session_name}' found.", file=sys.stderr)
        sys.exit(1)
    if not info.is_alive():
        print(f"Session '{session_name}' (PID {info.pid}) is not running (stale). Cleaning up.")
        remove_session(session_name)
        return

    print(f"Sending SIGTERM to '{session_name}' (PID {info.pid})…")
    if stop_session(info):
        print(f"Session '{session_name}' stopped.")
    else:
        print(f"Session '{session_name}' did not exit cleanly.", file=sys.stderr)
        sys.exit(1)
    _cleanup_pid_file()


def _stop_legacy_pid() -> None:
    """Stop a server process tracked only via a legacy PID file."""
    try:
        with open(_PID_FILE) as f:
            pid = int(f.read().strip())
    except FileNotFoundError:
        print("No running server found.")
        sys.exit(1)
    except (ValueError, OSError) as exc:
        print(f"Error reading PID file: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        print(f"Server process {pid} is not running (stale PID file). Cleaning up.")
        _cleanup_pid_file()
        return
    except PermissionError:
        pass

    print(f"Sending SIGTERM to server (PID {pid})…")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"Failed to stop server: {exc}", file=sys.stderr)
        sys.exit(1)

    import time

    for _ in range(30):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
    else:
        print(f"Server (PID {pid}) did not exit within 3 s — sending SIGKILL.")
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    _cleanup_pid_file()
    print("Server stopped.")


def _cmd_stop(args: argparse.Namespace) -> None:
    """Entry-point for ``argus-mcp stop [NAME] [--all] [--force]``."""
    from argus_mcp.sessions import (
        discover_server_processes,
        find_session,
        list_sessions,
        stop_pid,
        stop_session,
    )

    stop_all: bool = getattr(args, "all", False)
    force: bool = getattr(args, "force", False)
    session_name: Optional[str] = getattr(args, "session_name", None)

    if stop_all:
        _stop_all_servers(force=force)
        return

    if session_name:
        # Check if the name is actually a PID
        if session_name.isdigit():
            pid = int(session_name)
            print(f"Sending {'SIGKILL' if force else 'SIGTERM'} to PID {pid}…")
            if stop_pid(pid, force=force):
                print(f"Process {pid} stopped.")
            else:
                print(f"Process {pid} did not exit cleanly.", file=sys.stderr)
                sys.exit(1)
            _cleanup_pid_file()
            return
        _stop_named_session(session_name)
        return

    # No name given — try to find the only running session
    info = find_session()
    if info is not None:
        print(f"Sending SIGTERM to '{info.name}' (PID {info.pid})…")
        if stop_session(info, force=force):
            print(f"Session '{info.name}' stopped.")
        else:
            print(f"Session '{info.name}' did not exit cleanly.", file=sys.stderr)
            sys.exit(1)
        _cleanup_pid_file()
        return

    # Multiple sessions running
    alive = list_sessions()
    if len(alive) > 1:
        print("Multiple sessions running. Specify which one to stop:", file=sys.stderr)
        for s in alive:
            print(f"  {s.name:20s}  PID {s.pid:>6d}  port {s.port}", file=sys.stderr)
        print(
            "\nUsage: argus-mcp stop <name|pid>\n       argus-mcp stop --all",
            file=sys.stderr,
        )
        sys.exit(1)

    # Check for orphan processes not tracked by sessions
    orphans = discover_server_processes()
    if orphans:
        print("No registered sessions, but found orphan Argus server process(es):", file=sys.stderr)
        for o in orphans:
            print(f"  PID {o.pid:>6d}  {o.cmdline[:80]}", file=sys.stderr)
        print(
            "\nUse:  argus-mcp stop <PID>\n      argus-mcp stop --all",
            file=sys.stderr,
        )
        sys.exit(1)

    # Fall back to legacy PID file
    _stop_legacy_pid()


def _stop_all_servers(*, force: bool = False) -> None:
    """Stop all tracked sessions and orphan server processes."""
    from argus_mcp.sessions import (
        discover_server_processes,
        list_sessions,
        stop_pid,
        stop_session,
    )

    sessions = list_sessions()
    orphans = discover_server_processes()

    if not sessions and not orphans:
        print("No running Argus servers found.")
        return

    failed = 0
    for s in sessions:
        label = f"session '{s.name}' (PID {s.pid})"
        print(f"Stopping {label}…")
        if stop_session(s, force=force):
            print(f"  ✓ {label} stopped.")
        else:
            print(f"  ✗ {label} did not exit cleanly.", file=sys.stderr)
            failed += 1

    for o in orphans:
        label = f"orphan PID {o.pid}"
        print(f"Stopping {label}…")
        if stop_pid(o.pid, force=force):
            print(f"  ✓ {label} stopped.")
        else:
            print(f"  ✗ {label} did not exit cleanly.", file=sys.stderr)
            failed += 1

    _cleanup_pid_file()

    total = len(sessions) + len(orphans)
    print(f"\n{total - failed}/{total} server(s) stopped.")
    if failed:
        sys.exit(1)


def _cmd_status(_args: argparse.Namespace) -> None:
    """Entry-point for ``argus-mcp status``."""
    from argus_mcp.sessions import discover_server_processes, list_sessions

    sessions = list_sessions()
    orphans = discover_server_processes()

    if not sessions and not orphans:
        print("No running Argus MCP servers.")
        return

    if sessions:
        print(
            f"{'NAME':<20s}  {'PID':>6s}  {'PORT':>5s}  {'HOST':<15s}  {'CONFIG':<30s}  {'STARTED'}"
        )
        print("─" * 100)
        for s in sessions:
            started = s.started_at[:19].replace("T", " ") if s.started_at else "unknown"
            config_display = os.path.basename(s.config) if s.config else "-"
            print(
                f"{s.name:<20s}  {s.pid:>6d}  {s.port:>5d}  {s.host:<15s}  "
                f"{config_display:<30s}  {started}"
            )
        print(f"\n{len(sessions)} registered session(s).")

    if orphans:
        if sessions:
            print()
        print("Unregistered server processes (no session file):")
        print(f"  {'PID':>6s}  {'STARTED':<20s}  {'COMMAND'}")
        print(f"  {'─' * 6}  {'─' * 20}  {'─' * 70}")
        for o in orphans:
            started = o.started or "unknown"
            cmd = o.cmdline[:70]
            print(f"  {o.pid:>6d}  {started:<20s}  {cmd}")
        print(f"\n{len(orphans)} unregistered process(es).")
        print("Tip: argus-mcp stop <PID>  or  argus-mcp stop --all")
