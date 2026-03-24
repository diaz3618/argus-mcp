"""Container / image / network cleanup for ``argus-mcp clean``."""

from __future__ import annotations

import argparse
import subprocess

_BATCH_SIZE = 10
_BATCH_TIMEOUT = 120
_INDIVIDUAL_TIMEOUT = 30


def _detect_container_runtime() -> str:
    """Return ``'docker'`` or ``'podman'``, whichever is available first."""
    for candidate in ("docker", "podman"):
        try:
            subprocess.run(
                [candidate, "version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
            return candidate
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    return "docker"


def _batch_remove(
    runtime: str,
    subcommand: list[str],
    ids: list[str],
    *,
    label: str = "item",
    batch_size: int = _BATCH_SIZE,
    batch_timeout: int = _BATCH_TIMEOUT,
    individual_timeout: int = _INDIVIDUAL_TIMEOUT,
) -> tuple[int, int]:
    """Remove *ids* via *runtime* in batches with progressive retry.

    Returns ``(removed, failed)`` counts.
    """
    removed = 0
    failed = 0
    total = len(ids)

    for i in range(0, total, batch_size):
        batch = ids[i : i + batch_size]
        try:
            subprocess.run(
                [runtime, *subcommand, *batch],
                capture_output=True,
                timeout=batch_timeout,
            )
            removed += len(batch)
        except subprocess.TimeoutExpired:
            # Progressive retry: attempt each item individually
            for item in batch:
                try:
                    subprocess.run(
                        [runtime, *subcommand, item],
                        capture_output=True,
                        timeout=individual_timeout,
                    )
                    removed += 1
                except subprocess.TimeoutExpired:
                    failed += 1

        if total > batch_size:
            print(f"  Progress: {removed + failed}/{total} {label}(s) processed")

    return removed, failed


def _find_argus_containers(
    runtime: str,
    image_prefix: str,
) -> tuple[list[str], list[str]]:
    """Return ``(container_ids, display_lines)`` for argus-mcp containers."""
    result = subprocess.run(
        [
            runtime,
            "ps",
            "-a",
            "--filter",
            f"ancestor={image_prefix}/",
            "--format",
            "{{.ID}} {{.Names}} {{.Image}} {{.Status}}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    result2 = subprocess.run(
        [
            runtime,
            "ps",
            "-a",
            "--format",
            "{{.ID}} {{.Names}} {{.Image}} {{.Status}}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    container_lines: list[str] = []
    container_ids: list[str] = []
    seen: set[str] = set()
    for line in (result.stdout + "\n" + result2.stdout).strip().splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        cid, image = parts[0], parts[2]
        if cid in seen:
            continue
        if image.startswith(f"{image_prefix}/"):
            seen.add(cid)
            container_ids.append(cid)
            container_lines.append(line)
    return container_ids, container_lines


def _clean_images(runtime: str, image_prefix: str) -> None:
    """Find and batch-remove ``arguslocal/`` images."""
    img_result = subprocess.run(
        [
            runtime,
            "images",
            "--format",
            "{{.ID}} {{.Repository}}:{{.Tag}}",
            f"{image_prefix}/*",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    image_ids: list[str] = []
    image_lines: list[str] = []
    for line in img_result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if parts:
            image_ids.append(parts[0])
            image_lines.append(line)

    if image_ids:
        print(f"\nRemoving {len(image_ids)} arguslocal image(s):")
        for line in image_lines:
            print(f"  {line}")
        removed, failed = _batch_remove(
            runtime,
            ["rmi", "-f"],
            image_ids,
            label="image",
        )
        if failed:
            print(f"  {failed} image(s) could not be removed (timeout).")
        else:
            print(f"  {removed} image(s) removed.")
    else:
        print("\nNo arguslocal images found.")


def _clean_network(runtime: str) -> None:
    """Find and remove the argus-mcp Docker network."""
    from argus_mcp.bridge.container.network import ARGUS_NETWORK

    net_result = subprocess.run(
        [runtime, "network", "ls", "--filter", f"name={ARGUS_NETWORK}", "-q"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    net_ids = net_result.stdout.strip().splitlines()
    if net_ids:
        print(f"\nRemoving '{ARGUS_NETWORK}' network…")
        try:
            subprocess.run(
                [runtime, "network", "rm", ARGUS_NETWORK],
                capture_output=True,
                timeout=30,
            )
            print("Network removed.")
        except subprocess.TimeoutExpired:
            print("  Warning: network removal timed out.")
    else:
        print(f"\nNo '{ARGUS_NETWORK}' network found.")


def _cmd_clean(args: argparse.Namespace) -> None:
    """Remove containers and images created by argus-mcp.

    Finds containers whose image starts with ``arguslocal/`` and
    removes them.  Optionally removes the ``arguslocal/`` images
    and the ``argus-mcp`` Docker network as well.
    """
    from argus_mcp.bridge.container.templates import IMAGE_PREFIX

    images_flag: bool = getattr(args, "images", False)
    network_flag: bool = getattr(args, "network", False)
    all_flag: bool = getattr(args, "all", False)
    if all_flag:
        images_flag = network_flag = True

    runtime = _detect_container_runtime()

    container_ids, container_lines = _find_argus_containers(runtime, IMAGE_PREFIX)

    if container_ids:
        print(f"Removing {len(container_ids)} argus-mcp container(s):")
        for line in container_lines:
            print(f"  {line}")
        removed, failed = _batch_remove(
            runtime,
            ["rm", "-f"],
            container_ids,
            label="container",
            batch_timeout=60,
        )
        if failed:
            print(f"  Warning: {failed} container(s) could not be removed (timeout).")
        else:
            print(f"  {removed} container(s) removed.")
    else:
        print("No argus-mcp containers found.")

    if images_flag:
        _clean_images(runtime, IMAGE_PREFIX)

    if network_flag:
        _clean_network(runtime)
