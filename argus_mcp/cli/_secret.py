"""``argus-mcp secret`` subcommand implementation."""

from __future__ import annotations

import argparse
import sys


def _cmd_secret(args: argparse.Namespace) -> None:
    """Entry-point for ``argus-mcp secret set/get/list/delete``."""
    from argus_mcp.secrets.store import SecretStore

    provider = getattr(args, "provider", "file")
    store_kwargs: dict[str, str] = {}
    if provider == "file":
        path = getattr(args, "path", None) or "secrets.enc"
        store_kwargs["path"] = path

    store = SecretStore(provider_type=provider, **store_kwargs)
    action = args.secret_action

    if action == "set":
        import getpass as _gp

        value = getattr(args, "value", None)
        if value is None:
            value = _gp.getpass(f"Value for '{args.name}': ")
        store.set(args.name, value)
        print(f"Secret '{args.name}' stored.")

    elif action == "get":
        val = store.get(args.name)
        if val is None:
            print(f"Secret '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        print(val)

    elif action == "list":
        names = store.list_names()
        if not names:
            print("No secrets stored.")
        else:
            for n in sorted(names):
                print(n)

    elif action == "delete":
        store.delete(args.name)
        print(f"Secret '{args.name}' deleted.")
