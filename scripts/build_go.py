#!/usr/bin/env python3
"""Build the argusd Go daemon.

Checks for Go toolchain availability and builds the argusd binary
in packages/argusd/.

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


def _check_toolchain() -> bool:
    """Check that go is available."""
    return shutil.which("go") is not None


def _build(target: str = "build") -> bool:
    """Run make target in the argusd directory. Returns True on success."""
    if not ARGUSD_DIR.is_dir():
        print(f"argusd directory not found: {ARGUSD_DIR}")
        return False

    makefile = ARGUSD_DIR / "Makefile"
    if not makefile.exists():
        print(f"No Makefile in {ARGUSD_DIR}")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build argusd Go daemon")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check Go toolchain availability",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Cross-compile for all platforms (linux/darwin amd64/arm64)",
    )
    args = parser.parse_args()

    if not _check_toolchain():
        print(
            "Go toolchain not available.\n"
            "argusd is optional — container/k8s management features will be disabled.\n"
            "To install: https://go.dev/dl/"
        )
        return 0 if not args.check else 1

    if args.check:
        print("Go toolchain available")
        return 0

    target = "build-all" if args.all else "build"
    if _build(target):
        binary = ARGUSD_DIR / "argusd"
        if binary.exists() and not args.all:
            print(f"\nargusd binary: {binary}")
        elif args.all:
            dist = ARGUSD_DIR / "dist"
            if dist.exists():
                print(f"\nCross-compiled binaries in: {dist}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
