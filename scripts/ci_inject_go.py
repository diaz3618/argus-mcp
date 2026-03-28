#!/usr/bin/env python3
"""Inject pre-built Go binaries into argus_mcp/_bin/ for wheel packaging.

Called by cibuildwheel's ``before-build`` hook. Auto-detects the target
platform from environment variables set by cibuildwheel, or accepts
explicit ``--os`` / ``--arch`` flags.

Usage (CI — auto-detect from cibuildwheel env):
    python scripts/ci_inject_go.py --auto

Usage (manual):
    python scripts/ci_inject_go.py --os linux --arch amd64
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "argus_mcp" / "_bin"

# Go binary names (without .exe suffix).
GO_BINARIES = ["docker-adapter", "mcp-stdio-wrapper"]


def _detect_platform() -> tuple[str, str]:
    """Detect OS and arch from cibuildwheel env or the running system."""
    # cibuildwheel sets AUDITWHEEL_PLAT (linux) or CIBW_PLATFORM (all).
    plat = os.environ.get("AUDITWHEEL_PLAT", "")
    if "aarch64" in plat:
        return "linux", "arm64"
    if "x86_64" in plat:
        return "linux", "amd64"

    # Fall back to Python platform detection.
    system = platform.system().lower()
    machine = platform.machine().lower()
    os_name = {"linux": "linux", "darwin": "darwin", "windows": "windows"}.get(system, system)
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine
    )
    return os_name, arch


def _find_staging_dir(os_name: str, arch: str) -> Path:
    """Locate the staging directory with pre-built Go binaries.

    CI downloads Go artifacts into ``go-binaries/`` at the project root.
    The expected layout is::

        go-binaries/{os}_{arch}/docker-adapter
        go-binaries/{os}_{arch}/mcp-stdio-wrapper
    """
    staging = ROOT / "go-binaries" / f"{os_name}_{arch}"
    if staging.is_dir():
        return staging

    # Flat layout fallback (all binaries in go-binaries/ directly).
    flat = ROOT / "go-binaries"
    if flat.is_dir():
        return flat

    raise FileNotFoundError(
        f"Go binary staging directory not found: {staging}\n"
        f"Run the build-go-binaries CI job first, or place binaries in {flat}"
    )


def inject(os_name: str, arch: str) -> None:
    """Copy Go binaries into argus_mcp/_bin/."""
    staging = _find_staging_dir(os_name, arch)
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    suffix = ".exe" if os_name == "windows" else ""
    copied = 0

    for name in GO_BINARIES:
        src = staging / f"{name}{suffix}"
        if not src.is_file():
            print(f"  SKIP {name} (not found at {src})")
            continue

        dst = BIN_DIR / f"{name}{suffix}"
        shutil.copy2(src, dst)
        # Ensure executable bit on Unix.
        if os_name != "windows":
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"  OK   {name} -> {dst}")
        copied += 1

    print(f"\nInjected {copied}/{len(GO_BINARIES)} Go binaries for {os_name}/{arch}")
    if copied == 0:
        print("WARNING: No Go binaries were injected.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject Go binaries into wheel")
    parser.add_argument("--auto", action="store_true", help="Auto-detect platform")
    parser.add_argument("--os", dest="os_name", help="Target OS (linux/darwin/windows)")
    parser.add_argument("--arch", help="Target arch (amd64/arm64)")
    args = parser.parse_args()

    if args.auto:
        os_name, arch = _detect_platform()
    elif args.os_name and args.arch:
        os_name, arch = args.os_name, args.arch
    else:
        parser.error("Use --auto or provide both --os and --arch")

    print(f"Injecting Go binaries for {os_name}/{arch}")
    inject(os_name, arch)


if __name__ == "__main__":
    main()
