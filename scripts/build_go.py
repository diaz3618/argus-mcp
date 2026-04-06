#!/usr/bin/env python3
"""Build Go binaries for argus-mcp.

Builds two Go components:
  - **argusd**: The daemon in ``packages/argusd/`` (via its Makefile).
  - **docker-adapter**: The Docker Engine API adapter in
    ``tools/docker-adapter/`` (via ``go build``).

Usage:
    python scripts/build_go.py            # build for current platform
    python scripts/build_go.py --check    # only verify Go is available
    python scripts/build_go.py --all      # cross-compile all platforms
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARGUSD_DIR = ROOT / "packages" / "argusd"
DOCKER_ADAPTER_DIR = ROOT / "tools" / "docker-adapter"


def _check_toolchain() -> bool:
    """Check that go is available."""
    return shutil.which("go") is not None


def _build_argusd(target: str = "build") -> bool:
    """Run make target in the argusd directory. Returns True on success."""
    if not ARGUSD_DIR.is_dir():
        print(f"  argusd directory not found: {ARGUSD_DIR}")
        return False

    makefile = ARGUSD_DIR / "Makefile"
    if not makefile.exists():
        print(f"  No Makefile in {ARGUSD_DIR}")
        return False

    print(f"  Building argusd ({target}) ...", end=" ", flush=True)
    result = subprocess.run(
        ["make", target],
        cwd=ARGUSD_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("OK")
        return True
    else:
        print("FAILED")
        if result.stderr:
            for line in result.stderr.strip().splitlines()[-5:]:
                print(f"    {line}")
        return False


def _build_docker_adapter() -> bool:
    """Build the docker-adapter Go binary. Returns True on success."""
    if not DOCKER_ADAPTER_DIR.is_dir():
        print(f"  docker-adapter directory not found: {DOCKER_ADAPTER_DIR}")
        return False

    go_mod = DOCKER_ADAPTER_DIR / "go.mod"
    if not go_mod.exists():
        print(f"  No go.mod in {DOCKER_ADAPTER_DIR}")
        return False

    print("  Building docker-adapter ...", end=" ", flush=True)
    result = subprocess.run(
        ["go", "build", "-o", "docker-adapter", "."],
        cwd=DOCKER_ADAPTER_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("OK")
        return True
    else:
        print("FAILED")
        if result.stderr:
            for line in result.stderr.strip().splitlines()[-5:]:
                print(f"    {line}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Go binaries (argusd + docker-adapter)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check Go toolchain availability",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Cross-compile argusd for all platforms (linux/darwin amd64/arm64)",
    )
    args = parser.parse_args()

    if not _check_toolchain():
        print(
            "Go toolchain not available.\n"
            "Go binaries are optional — Python fallbacks will be used.\n"
            "To install: https://go.dev/dl/"
        )
        return 0 if not args.check else 1

    if args.check:
        print("Go toolchain available")
        return 0

    ok_count = 0
    fail_count = 0

    # 1. Build argusd.
    target = "build-all" if args.all else "build"
    if _build_argusd(target):
        ok_count += 1
        binary = ARGUSD_DIR / "argusd"
        if binary.exists() and not args.all:
            print(f"    → {binary}")
        elif args.all:
            dist = ARGUSD_DIR / "dist"
            if dist.exists():
                print(f"    → Cross-compiled binaries in: {dist}")
    else:
        fail_count += 1

    # 2. Build docker-adapter.
    if _build_docker_adapter():
        ok_count += 1
        binary = DOCKER_ADAPTER_DIR / "docker-adapter"
        if binary.exists():
            print(f"    → {binary}")
    else:
        fail_count += 1

    print(f"\nGo builds: {ok_count} succeeded, {fail_count} failed")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
