#!/usr/bin/env python3
"""Verify contents of argus-mcp wheel and sdist packages.

Checks 4 packaging invariants:
  1. All 4 .j2 Dockerfile templates are present
  2. Package version matches constants.py SERVER_VERSION
  3. No Rust target/ build artifacts leaked
  4. No unexpected compiled binaries in wrong locations

Usage:
    python scripts/verify_package.py dist/argus_mcp-0.8.3.tar.gz
    python scripts/verify_package.py dist/argus_mcp-0.8.3-*.whl
    python scripts/verify_package.py dist/   # verify all packages in dir

Exit code 0 = all checks pass, 1 = at least one failure.
"""

from __future__ import annotations

import glob
import re
import sys
import tarfile
import zipfile
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

REQUIRED_TEMPLATES = {
    "argus_mcp/bridge/container/templates/npx.dockerfile.j2",
    "argus_mcp/bridge/container/templates/uvx.dockerfile.j2",
    "argus_mcp/bridge/container/templates/go.dockerfile.j2",
    "argus_mcp/bridge/container/templates/source.dockerfile.j2",
}

RUST_ARTIFACT_EXTENSIONS = {".rlib", ".rmeta", ".d", ".fingerprint"}

COMPILED_EXTENSIONS = {".so", ".dylib", ".dll", ".pyd"}


# ── Archive helpers ──────────────────────────────────────────────────────────


def list_wheel(path: Path) -> list[str]:
    """List all paths inside a wheel (zip)."""
    with zipfile.ZipFile(path) as zf:
        return zf.namelist()


def read_wheel_file(path: Path, inner: str) -> str:
    """Read a specific file from inside a wheel."""
    with zipfile.ZipFile(path) as zf:
        return zf.read(inner).decode("utf-8", errors="replace")


def list_sdist(path: Path) -> list[str]:
    """List all paths inside an sdist (tar.gz)."""
    with tarfile.open(path, "r:gz") as tf:
        return tf.getnames()


def read_sdist_file(path: Path, inner: str) -> str:
    """Read a specific file from inside an sdist."""
    with tarfile.open(path, "r:gz") as tf:
        member = tf.getmember(inner)
        f = tf.extractfile(member)
        if f is None:
            return ""
        return f.read().decode("utf-8", errors="replace")


# ── Check functions ──────────────────────────────────────────────────────────


def check_templates(entries: list[str], is_sdist: bool) -> tuple[bool, str]:
    """Check that all 4 .j2 templates are present."""
    found = set()
    for entry in entries:
        # sdist entries have a top-level directory prefix like argus_mcp-0.8.3/
        normalized = "/".join(entry.split("/")[1:]) if is_sdist else entry
        for tpl in REQUIRED_TEMPLATES:
            if normalized == tpl or entry.endswith(tpl):
                found.add(tpl)

    missing = REQUIRED_TEMPLATES - found
    if missing:
        msg = f"Missing {len(missing)} template(s): {', '.join(sorted(missing))}"
        return False, msg
    return True, f"All {len(REQUIRED_TEMPLATES)} templates present"


def check_version(
    path: Path,
    entries: list[str],
    is_sdist: bool,
) -> tuple[bool, str]:
    """Check that package metadata version matches constants.py."""
    # Find constants.py in the archive
    constants_entry = None
    for entry in entries:
        if entry.endswith("argus_mcp/constants.py"):
            constants_entry = entry
            break

    if constants_entry is None:
        return False, "constants.py not found in archive"

    if is_sdist:
        constants_text = read_sdist_file(path, constants_entry)
    else:
        constants_text = read_wheel_file(path, constants_entry)

    match = re.search(r'SERVER_VERSION\s*=\s*"([^"]+)"', constants_text)
    if not match:
        return False, "SERVER_VERSION not found in constants.py"
    constants_ver = match.group(1)

    # Find metadata version
    meta_ver = None
    if is_sdist:
        for entry in entries:
            if entry.endswith("/PKG-INFO"):
                meta_text = read_sdist_file(path, entry)
                m = re.search(r"^Version:\s*(.+)$", meta_text, re.MULTILINE)
                if m:
                    meta_ver = m.group(1).strip()
                break
    else:
        for entry in entries:
            if entry.endswith(".dist-info/METADATA"):
                meta_text = read_wheel_file(path, entry)
                m = re.search(r"^Version:\s*(.+)$", meta_text, re.MULTILINE)
                if m:
                    meta_ver = m.group(1).strip()
                break

    if meta_ver is None:
        return False, "Could not extract version from package metadata"

    if meta_ver != constants_ver:
        return False, (f"Version mismatch: metadata={meta_ver} constants.py={constants_ver}")

    return True, f"Version consistent: {meta_ver}"


def check_no_target_artifacts(entries: list[str]) -> tuple[bool, str]:
    """Check that no Rust target/ build artifacts leaked."""
    leaked = []
    for entry in entries:
        parts = entry.split("/")
        # Check if 'target' appears as a directory component
        if "target" not in parts:
            continue
        target_idx = parts.index("target")
        # Only flag if it looks like a Rust build directory
        # (has sub-paths like debug/, release/, .fingerprint/)
        suffix = Path(entry).suffix
        if suffix in RUST_ARTIFACT_EXTENSIONS:
            leaked.append(entry)
        elif any(
            p in ("debug", "release", ".fingerprint", "build", "deps")
            for p in parts[target_idx + 1 :]
        ):
            leaked.append(entry)

    if leaked:
        sample = leaked[:5]
        msg = f"Found {len(leaked)} Rust target/ artifact(s): {', '.join(sample)}"
        if len(leaked) > 5:
            msg += f" ... and {len(leaked) - 5} more"
        return False, msg

    return True, "No Rust target/ artifacts found"


def check_no_unexpected_binaries(entries: list[str]) -> tuple[bool, str]:
    """Check no compiled binaries exist in unexpected locations."""
    unexpected = []
    for entry in entries:
        suffix = Path(entry).suffix
        if suffix not in COMPILED_EXTENSIONS:
            continue
        # PyO3 extensions live at argus_mcp/*.so (or .pyd on Windows)
        # and are expected at the top level of the package
        parts = entry.split("/")
        # Allow: argus_mcp/<name>.so, argus_mcp/<name>.pyd
        # Allow: argus_mcp-*.dist-info/ (wheel metadata)
        # Disallow: anything nested deeper (target/, build/)
        pkg_parts = [p for p in parts if not p.endswith(".dist-info")]
        if len(pkg_parts) <= 2:
            # Top-level in package: argus_mcp/something.so → OK
            continue
        unexpected.append(entry)

    if unexpected:
        sample = unexpected[:5]
        msg = f"Found {len(unexpected)} unexpected compiled binary(ies): {', '.join(sample)}"
        if len(unexpected) > 5:
            msg += f" ... and {len(unexpected) - 5} more"
        return False, msg

    return True, "No unexpected compiled binaries"


# ── Main ─────────────────────────────────────────────────────────────────────


def verify_package(path: Path) -> bool:
    """Run all checks on a single package file. Returns True if all pass."""
    is_sdist = path.name.endswith(".tar.gz")
    is_wheel = path.name.endswith(".whl")

    if not (is_sdist or is_wheel):
        print(f"  ⏭  Skipping (not a wheel or sdist): {path.name}")
        return True

    pkg_type = "sdist" if is_sdist else "wheel"
    print(f"\n{'─' * 60}")
    print(f"  Verifying {pkg_type}: {path.name}")
    print(f"{'─' * 60}")

    entries = list_sdist(path) if is_sdist else list_wheel(path)

    checks = [
        ("Templates (.j2)", check_templates(entries, is_sdist)),
        ("Version consistency", check_version(path, entries, is_sdist)),
        ("No Rust target/ artifacts", check_no_target_artifacts(entries)),
        ("No unexpected binaries", check_no_unexpected_binaries(entries)),
    ]

    all_pass = True
    for name, (passed, msg) in checks:
        icon = "✅" if passed else "❌"
        print(f"  {icon} {name}: {msg}")
        if not passed:
            all_pass = False
            # GitHub Actions error annotation
            print(f"::error file={path}::{name}: {msg}")

    return all_pass


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-package-or-directory> [...]")
        return 1

    packages: list[Path] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            packages.extend(sorted(p.glob("argus_mcp*.whl")))
            packages.extend(sorted(p.glob("argus_mcp*.tar.gz")))
            # Also search subdirectories (download-artifact creates them)
            packages.extend(sorted(p.glob("**/argus_mcp*.whl")))
            packages.extend(sorted(p.glob("**/argus_mcp*.tar.gz")))
            # Deduplicate while preserving order
            seen = set()
            deduped = []
            for pkg in packages:
                resolved = pkg.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    deduped.append(pkg)
            packages = deduped
        elif p.is_file():
            packages.append(p)
        else:
            # Try glob expansion
            expanded = glob.glob(arg)
            packages.extend(Path(x) for x in sorted(expanded))

    if not packages:
        print("❌ No packages found to verify")
        print("::error::No argus-mcp packages found in specified path(s)")
        return 1

    print(f"Found {len(packages)} package(s) to verify")

    all_pass = True
    for pkg in packages:
        if not verify_package(pkg):
            all_pass = False

    print(f"\n{'═' * 60}")
    if all_pass:
        print("  ✅ ALL CHECKS PASSED")
    else:
        print("  ❌ SOME CHECKS FAILED")
    print(f"{'═' * 60}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
