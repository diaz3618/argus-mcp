#!/usr/bin/env python3
"""Build all Rust PyO3 extensions in the project.

Discovers Rust crate directories (Cargo.toml + maturin pyproject.toml),
builds each with ``maturin develop --release``, and reports results.

Usage:
    python scripts/build_rust.py           # build all crates
    python scripts/build_rust.py --check   # only verify toolchain availability
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Project root — parent of the scripts/ directory
ROOT = Path(__file__).resolve().parent.parent

# Directories to skip when scanning for Rust crates
SKIP_DIRS = {"internal", ".venv", ".git", "target", "node_modules"}

MATURIN_BUILD_BACKEND = "maturin"


def _find_rust_crates(root: Path) -> list[Path]:
    """Return directories containing both Cargo.toml and a maturin pyproject.toml."""
    crates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune directories we never want to descend into
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        p = Path(dirpath)
        if "Cargo.toml" in filenames and "pyproject.toml" in filenames:
            # Verify it uses maturin as the build backend
            pyproject = p / "pyproject.toml"
            try:
                text = pyproject.read_text(encoding="utf-8")
                if MATURIN_BUILD_BACKEND in text:
                    crates.append(p)
            except OSError:
                pass
    return sorted(crates)


def _check_toolchain() -> tuple[bool, list[str]]:
    """Check that cargo and maturin are available. Returns (ok, missing)."""
    missing: list[str] = []
    for cmd in ("cargo", "maturin"):
        if shutil.which(cmd) is None:
            missing.append(cmd)
    return len(missing) == 0, missing


def _build_crate(crate_dir: Path, *, release: bool = True) -> bool:
    """Build a single Rust crate with maturin develop. Returns True on success."""
    cmd = ["maturin", "develop"]
    if release:
        cmd.append("--release")

    print(f"  Building {crate_dir.relative_to(ROOT)} ...", end=" ", flush=True)
    result = subprocess.run(
        cmd,
        cwd=crate_dir,
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
    parser = argparse.ArgumentParser(description="Build Rust PyO3 extensions")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check toolchain availability, don't build",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build in debug mode instead of release",
    )
    args = parser.parse_args()

    # Check toolchain
    ok, missing = _check_toolchain()
    if not ok:
        print(
            f"Rust toolchain not available (missing: {', '.join(missing)}).\n"
            "Rust extensions are optional — Python fallbacks will be used.\n"
            "To install: https://rustup.rs/ and `pip install maturin`"
        )
        return 0 if not args.check else 1

    if args.check:
        print("Rust toolchain available: cargo + maturin found")
        return 0

    # Discover crates
    crates = _find_rust_crates(ROOT)
    if not crates:
        print("No Rust crates found.")
        return 0

    print(f"Found {len(crates)} Rust crate(s):")
    for c in crates:
        print(f"  - {c.relative_to(ROOT)}")
    print()

    # Build each crate
    ok_count = 0
    fail_count = 0
    for crate_dir in crates:
        if _build_crate(crate_dir, release=not args.debug):
            ok_count += 1
        else:
            fail_count += 1

    print(f"\nResults: {ok_count} built, {fail_count} failed")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
