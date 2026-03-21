"""Container image pre-build for ``argus-mcp build``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from argus_mcp.config.loader import find_config_file as _find_config_file
from argus_mcp.display.logging_config import setup_logging


async def _pre_pull_base_images(
    jobs: list[tuple[str, dict]],
    log: logging.Logger,
    verbosity: int,
) -> None:
    """Pull unique base images in parallel before builds start.

    This ensures the first build for each transport doesn't block on
    a base-image pull, and when running parallel builds the pulls don't
    compete with each other.
    """
    from argus_mcp.bridge.container.image_builder import classify_command
    from argus_mcp.bridge.container.runtime import DockerRuntime
    from argus_mcp.bridge.container.templates import RUNTIME_DEFAULTS

    images_needed: set[str] = set()
    for _name, kw in jobs:
        builder = kw.get("builder_image")
        if builder:
            images_needed.add(builder)
            continue
        cmd = kw.get("params")
        if cmd is not None:
            transport = kw.get("transport_override") or classify_command(cmd.command)
            if transport and transport in RUNTIME_DEFAULTS:
                images_needed.add(str(RUNTIME_DEFAULTS[transport]["builder_image"]))

    if not images_needed:
        return

    rt = DockerRuntime()
    # Only pull images not already available locally
    to_pull: list[str] = []
    for img in images_needed:
        if not await rt.image_exists(img):
            to_pull.append(img)

    if not to_pull:
        return

    if verbosity >= 0:
        print(f"  Pre-pulling {len(to_pull)} base image(s): {', '.join(to_pull)}")

    results = await asyncio.gather(
        *(rt.pull_image(img) for img in to_pull),
        return_exceptions=True,
    )
    for img, result in zip(to_pull, results):
        if isinstance(result, BaseException):
            log.warning("Failed to pre-pull %s: %s", img, result)
        elif not result:
            log.warning("Failed to pre-pull %s", img)


def _cmd_build(args: argparse.Namespace) -> None:
    """Pre-build container images for all stdio backends.

    By default builds images **concurrently** (parallel).  Pass
    ``--no-parallel`` to build sequentially one at a time.

    This should be run once before ``argus-mcp server`` when container
    isolation is enabled (the default).
    """
    config_path = getattr(args, "config", None) or _find_config_file()
    parallel = getattr(args, "parallel", True)
    verbosity = -1 if getattr(args, "quiet", False) else (getattr(args, "verbose", 0) or 0)
    setup_logging("info")

    log = logging.getLogger("argus_mcp.build")
    log.info("Loading config from %s", config_path)

    from argus_mcp.config.loader import load_and_validate_config

    backend_map = load_and_validate_config(config_path)

    # Identify stdio backends
    stdio_backends = {
        name: conf for name, conf in backend_map.items() if conf.get("type") == "stdio"
    }

    if not stdio_backends:
        print("No stdio backends found in config — nothing to build.")
        return

    mode_label = "concurrently" if parallel else "sequentially"
    if verbosity >= 0:
        print(
            f"Building container images for {len(stdio_backends)} stdio backend(s) ({mode_label})...\n"
        )

    async def _build_all() -> None:
        from mcp import StdioServerParameters

        from argus_mcp.bridge.container import wrap_backend

        def _build_kwargs(name: str, conf: dict) -> dict | None:
            """Return wrap_backend kwargs or None if the backend should be skipped."""
            params = conf.get("params")
            if not isinstance(params, StdioServerParameters):
                log.warning("[%s] Invalid params — skipping.", name)
                return None
            container_cfg = conf.get("container") or {}
            net_override = container_cfg.get("network") or (
                (conf.get("network") or {}).get("network_mode")
            )
            return {
                "name": name,
                "params": params,
                "enabled": container_cfg.get("enabled", True),
                "runtime_override": container_cfg.get("runtime"),
                "network": net_override,
                "memory": container_cfg.get("memory"),
                "cpus": container_cfg.get("cpus"),
                "volumes": container_cfg.get("volumes"),
                "extra_args": container_cfg.get("extra_args"),
                "build_if_missing": True,
                "system_deps": container_cfg.get("system_deps"),
                "build_system_deps": container_cfg.get("build_system_deps"),
                "builder_image": container_cfg.get("builder_image"),
                "additional_packages": container_cfg.get("additional_packages"),
                "transport_override": container_cfg.get("transport"),
                "go_package": container_cfg.get("go_package"),
                "source_url": container_cfg.get("source_url"),
                "build_steps": container_cfg.get("build_steps"),
                "entrypoint": container_cfg.get("entrypoint"),
                "build_env": container_cfg.get("build_env"),
                "source_ref": container_cfg.get("source_ref"),
                "dockerfile": container_cfg.get("dockerfile"),
            }

        async def _do_build(name: str, kw: dict) -> tuple[str, str]:
            """Run a single build and return (name, 'ok'|'skip'|'fail')."""
            try:
                _wrapped, was_isolated = await wrap_backend(**kw)
                return (name, "ok" if was_isolated else "skip")
            except Exception as exc:  # noqa: BLE001
                log.error("[%s] Build failed: %s", name, exc, exc_info=True)
                return (name, "fail")

        # Collect valid build jobs
        jobs: list[tuple[str, dict]] = []
        skip = 0
        for name, conf in stdio_backends.items():
            kw = _build_kwargs(name, conf)
            if kw is None:
                skip += 1
            else:
                jobs.append((name, kw))

        # Pre-warm base images so individual builds don't block on pulls
        await _pre_pull_base_images(jobs, log, verbosity)

        if parallel and len(jobs) > 1:
            if verbosity >= 0:
                print(f"  Launching {len(jobs)} builds in parallel ...")
            results = await asyncio.gather(
                *(_do_build(n, kw) for n, kw in jobs),
                return_exceptions=True,
            )
            ok = fail = 0
            for res in results:
                if isinstance(res, BaseException):
                    fail += 1
                    log.error("Unexpected build error: %s", res)
                else:
                    bname, status = res
                    if status == "ok":
                        if verbosity >= 0:
                            print(f"  [{bname}] OK (containerised)")
                        ok += 1
                    elif status == "skip":
                        if verbosity >= 0:
                            print(f"  [{bname}] skipped (not wrappable or disabled)")
                        skip += 1
                    else:
                        print(f"  [{bname}] FAILED", file=sys.stderr)
                        fail += 1
        else:
            ok = fail = 0
            for name, kw in jobs:
                if verbosity >= 0:
                    print(
                        f"  [{name}] Building image for '{kw['params'].command}' ...",
                        end=" ",
                        flush=True,
                    )
                bname, status = await _do_build(name, kw)
                if status == "ok":
                    if verbosity >= 0:
                        print("OK (containerised)")
                    ok += 1
                elif status == "skip":
                    if verbosity >= 0:
                        print("skipped (not wrappable or disabled)")
                    skip += 1
                else:
                    if verbosity >= 0:
                        print("FAILED")
                    fail += 1

        if verbosity >= 0:
            print(f"\nDone: {ok} built, {skip} skipped, {fail} failed.")
        if fail > 0:
            sys.exit(1)

    asyncio.run(_build_all())
