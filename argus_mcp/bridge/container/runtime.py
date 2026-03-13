"""Container runtime detection, abstraction, and management.

Provides a pluggable runtime layer with a factory pattern so that
Docker and Kubernetes are both first-class container runtimes, with
auto-detection and explicit override via ``ARGUS_RUNTIME``.

Runtime priority (lower wins):
    Docker / Podman  — priority 100 / 110 (preferred)
    Kubernetes       — priority 200

Architecture
------------
:class:`ContainerRuntime`
    Abstract base class defining the interface every runtime must
    implement: health check, image management, and container lifecycle.

:class:`DockerRuntime`
    Concrete implementation for Docker / Podman (CLI-based).

:class:`KubernetesRuntime`
    Placeholder for future Kubernetes support via the ``kubernetes``
    Python client.  Not yet implemented.

:class:`RuntimeFactory`
    Singleton factory that auto-detects the best available runtime or
    respects the ``ARGUS_RUNTIME`` env-var override.
"""

from __future__ import annotations

import abc
import asyncio
import enum
import logging
import os
import shutil
import subprocess
from typing import Callable, ClassVar, List, Optional, Type

logger = logging.getLogger(__name__)

_HEALTH_CHECK_TIMEOUT: float = 10.0


class RuntimeType(str, enum.Enum):
    """Supported container runtime backends."""

    DOCKER = "docker"
    PODMAN = "podman"
    KUBERNETES = "kubernetes"

    @classmethod
    def from_str(cls, value: str) -> "RuntimeType":
        """Parse a string to a RuntimeType, case-insensitive."""
        normalised = value.strip().lower()
        aliases = {"k8s": "kubernetes", "kube": "kubernetes"}
        normalised = aliases.get(normalised, normalised)
        try:
            return cls(normalised)
        except ValueError:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(f"Unknown container runtime '{value}'. Valid: {valid}") from None


class ContainerRuntime(abc.ABC):
    """Abstract container runtime interface.

    Every runtime (Docker, Podman, Kubernetes) must implement this
    contract.  The public API mirrors what the wrapper and image-builder
    modules need.
    """

    @property
    @abc.abstractmethod
    def runtime_type(self) -> RuntimeType:
        """Return the type of this runtime."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable runtime name (e.g. ``'docker'``, ``'podman'``)."""

    @abc.abstractmethod
    async def is_healthy(self) -> bool:
        """Return ``True`` if the runtime daemon is responsive."""

    @abc.abstractmethod
    async def image_exists(self, image_tag: str) -> bool:
        """Check whether *image_tag* exists in the local image store."""

    @abc.abstractmethod
    async def build_image(
        self,
        context_dir: str,
        image_tag: str,
        *,
        dockerfile: str = "Dockerfile",
        line_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Build a container image and return ``True`` on success.

        Parameters
        ----------
        line_callback:
            If provided, called with each build output line so callers
            can stream progress to the user.
        """

    @abc.abstractmethod
    async def pull_image(self, image: str) -> bool:
        """Pull an image from a remote registry."""

    @abc.abstractmethod
    async def remove_image(self, image_tag: str) -> None:
        """Remove a local image (best-effort)."""

    @abc.abstractmethod
    async def create_network(
        self,
        network_name: str,
        *,
        internal: bool = False,
    ) -> bool:
        """Create a container network.

        Return ``True`` on success or if it already exists.
        """

    @abc.abstractmethod
    async def remove_network(self, network_name: str) -> None:
        """Remove a container network (best-effort)."""

    @abc.abstractmethod
    async def list_images(self, prefix: str = "") -> List[str]:
        """List local image tags matching an optional prefix."""


class DockerRuntime(ContainerRuntime):
    """Docker / Podman CLI-based container runtime."""

    PRIORITY: ClassVar[int] = 100

    def __init__(self, binary: str = "docker") -> None:
        self._binary = binary
        self._healthy: Optional[bool] = None

    @property
    def runtime_type(self) -> RuntimeType:
        if self._binary == "podman":
            return RuntimeType.PODMAN
        return RuntimeType.DOCKER

    @property
    def name(self) -> str:
        return self._binary

    def reset_health_cache(self) -> None:
        """Reset cached health state (for testing)."""
        self._healthy = None

    async def is_healthy(self) -> bool:
        if self._healthy is not None:
            return self._healthy
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            rc = await asyncio.wait_for(
                proc.wait(),
                timeout=_HEALTH_CHECK_TIMEOUT,
            )
            self._healthy = rc == 0
        except asyncio.TimeoutError:
            logger.warning(
                "Container runtime '%s' health check timed out after %.0fs.",
                self._binary,
                _HEALTH_CHECK_TIMEOUT,
            )
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                logger.debug("Container cleanup operation failed", exc_info=True)
            self._healthy = False
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(
                "Container runtime '%s' health check failed: %s.",
                self._binary,
                exc,
            )
            self._healthy = False
        return self._healthy

    async def image_exists(self, image_tag: str) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "image",
                "inspect",
                image_tag,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            rc = await proc.wait()
            return rc == 0
        except (OSError, FileNotFoundError) as exc:
            logger.debug("image_exists check failed for '%s': %s", image_tag, exc)
            return False

    async def build_image(
        self,
        context_dir: str,
        image_tag: str,
        *,
        dockerfile: str = "Dockerfile",
        line_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        logger.info("Building image '%s' from '%s'…", image_tag, context_dir)
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "build",
                "--progress=plain",
                "-t",
                image_tag,
                "-f",
                dockerfile,
                context_dir,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            # Stream stderr line-by-line so callers can display build
            # progress live.  Falls back to communicate() if no callback.
            if line_callback and proc.stderr:
                err_lines: list[str] = []
                while True:
                    raw = await proc.stderr.readline()
                    if not raw:
                        break
                    line = raw.decode(errors="replace").rstrip()
                    if line:
                        err_lines.append(line)
                        line_callback(line)
                await proc.wait()
                if proc.returncode != 0:
                    logger.error(
                        "Image build failed for '%s': %s",
                        image_tag,
                        "\n".join(err_lines[-40:]),
                    )
                    return False
            else:
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    err_text = stderr.decode(errors="replace").strip() if stderr else ""
                    logger.error(
                        "Image build failed for '%s': %s",
                        image_tag,
                        err_text[-2000:],
                    )
                    return False
            logger.info("Image '%s' built successfully.", image_tag)
            return True
        except (OSError, asyncio.TimeoutError) as exc:
            logger.error("Error building image '%s': %s", image_tag, exc)
            return False

    async def pull_image(self, image: str) -> bool:
        logger.info("Pulling image '%s' via %s…", image, self._binary)
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "pull",
                image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(
                    "Failed to pull image '%s': %s",
                    image,
                    stderr.decode(errors="replace").strip(),
                )
                return False
            return True
        except (OSError, asyncio.TimeoutError) as exc:
            logger.error("Error pulling image '%s': %s", image, exc)
            return False

    async def remove_image(self, image_tag: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "rmi",
                "-f",
                image_tag,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except OSError:
            logger.debug("Container cleanup operation failed", exc_info=True)

    async def create_network(
        self,
        network_name: str,
        *,
        internal: bool = False,
    ) -> bool:
        # Check existence first
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "network",
                "inspect",
                network_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            rc = await proc.wait()
            if rc == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            logger.debug("Container cleanup operation failed", exc_info=True)

        cmd: List[str] = [self._binary, "network", "create"]
        if internal:
            cmd.append("--internal")
        cmd.append(network_name)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip() if stderr else ""
                logger.error(
                    "Failed to create network '%s': %s",
                    network_name,
                    err,
                )
                return False
            logger.info("Created container network '%s'.", network_name)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error(
                "Error creating network '%s': %s",
                network_name,
                exc,
            )
            return False

    async def remove_network(self, network_name: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "network",
                "rm",
                network_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:  # noqa: BLE001
            logger.debug("Container cleanup operation failed", exc_info=True)

    async def list_images(self, prefix: str = "") -> List[str]:
        try:
            cmd = [
                self._binary,
                "images",
                "--format",
                "{{.Repository}}:{{.Tag}}",
            ]
            if prefix:
                cmd.append(prefix + "*")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return []
            lines = stdout.decode(errors="replace").strip().splitlines()
            return [ln.strip() for ln in lines if ln.strip() and ln.strip() != "<none>:<none>"]
        except (OSError, FileNotFoundError) as exc:
            logger.debug("list_images failed: %s", exc)
            return []


class KubernetesRuntime(ContainerRuntime):
    """Kubernetes container runtime (Pod-based).

    This implementation will use the ``kubernetes`` Python client to
    manage MCP server Pods directly.  It is designed for environments
    where Argus itself runs inside a Kubernetes cluster.

    .. note::

        Kubernetes support is under active development.  The runtime
        auto-detects by checking ``KUBERNETES_SERVICE_HOST``.
    """

    PRIORITY: ClassVar[int] = 200

    def __init__(self, *, namespace: str = "default") -> None:
        self._namespace = namespace
        self._healthy: Optional[bool] = None

    @property
    def runtime_type(self) -> RuntimeType:
        return RuntimeType.KUBERNETES

    @property
    def name(self) -> str:
        return "kubernetes"

    @classmethod
    def is_available(cls) -> bool:
        """Return ``True`` if running inside a Kubernetes cluster."""
        return bool(os.environ.get("KUBERNETES_SERVICE_HOST"))

    async def is_healthy(self) -> bool:
        if self._healthy is not None:
            return self._healthy
        if not self.is_available():
            self._healthy = False
            return False
        try:
            from kubernetes import client, config

            config.load_incluster_config()
            v1 = client.CoreV1Api()
            await asyncio.get_event_loop().run_in_executor(
                None,
                v1.get_api_resources,
            )
            self._healthy = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Kubernetes runtime health check failed: %s. Falling back to Docker.",
                exc,
            )
            self._healthy = False
        return self._healthy

    async def image_exists(self, image_tag: str) -> bool:
        return False  # K8s pulls from registries

    async def build_image(
        self,
        context_dir: str,
        image_tag: str,
        *,
        dockerfile: str = "Dockerfile",
        line_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        logger.warning(
            "Kubernetes runtime does not support local image builds. "
            "Use a pre-built image or configure a registry. "
            "Image '%s' not built.",
            image_tag,
        )
        return False

    async def pull_image(self, image: str) -> bool:
        logger.info(
            "Kubernetes pulls images automatically; skipping explicit pull for '%s'.",
            image,
        )
        return True

    async def remove_image(self, image_tag: str) -> None:
        pass

    async def create_network(
        self,
        network_name: str,
        *,
        internal: bool = False,
    ) -> bool:
        logger.debug(
            "Kubernetes network isolation uses NetworkPolicies, not named networks.",
        )
        return True

    async def remove_network(self, network_name: str) -> None:
        pass

    async def list_images(self, prefix: str = "") -> List[str]:
        return []


class _RuntimeEntry:
    """Internal registry entry for a container runtime."""

    __slots__ = ("runtime_cls", "priority", "detector")

    def __init__(
        self,
        runtime_cls: Type[ContainerRuntime],
        priority: int,
        detector: Callable[[], bool],
    ) -> None:
        self.runtime_cls = runtime_cls
        self.priority = priority
        self.detector = detector


class RuntimeFactory:
    """Singleton factory that discovers and creates container runtimes.

    Self-registering factory with priority-based auto-detection:

    - Docker: priority 100 (preferred)
    - Podman: priority 110
    - Kubernetes: priority 200

    Override with ``ARGUS_RUNTIME=docker|podman|kubernetes``.
    """

    _instance: ClassVar[Optional["RuntimeFactory"]] = None
    _registry: ClassVar[List[_RuntimeEntry]] = []

    def __init__(self) -> None:
        self._cached_runtime: Optional[ContainerRuntime] = None
        if not RuntimeFactory._registry:
            self._register_defaults()

    @classmethod
    def _register_defaults(cls) -> None:
        """Register the built-in runtimes."""
        cls._registry.append(
            _RuntimeEntry(
                runtime_cls=DockerRuntime,
                priority=100,
                detector=lambda: shutil.which("docker") is not None,
            )
        )
        cls._registry.append(
            _RuntimeEntry(
                runtime_cls=DockerRuntime,
                priority=110,
                detector=lambda: shutil.which("podman") is not None,
            )
        )
        cls._registry.append(
            _RuntimeEntry(
                runtime_cls=KubernetesRuntime,
                priority=200,
                detector=KubernetesRuntime.is_available,
            )
        )
        cls._registry.sort(key=lambda e: e.priority)

    @classmethod
    def get(cls) -> "RuntimeFactory":
        """Get or create the singleton factory instance."""
        if cls._instance is None:
            cls._instance = RuntimeFactory()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None
        cls._registry.clear()

    def detect(
        self,
        override: Optional[str] = None,
    ) -> Optional[ContainerRuntime]:
        """Auto-detect (or explicitly select) a container runtime.

        Parameters
        ----------
        override:
            Explicit runtime name (``"docker"``, ``"podman"``,
            ``"kubernetes"``).  If ``None``, checks ``ARGUS_RUNTIME``
            env var, then auto-detects by priority.

        Returns
        -------
        A :class:`ContainerRuntime` instance or ``None`` if no runtime
        is available.
        """
        if self._cached_runtime is not None:
            return self._cached_runtime

        explicit = override or os.environ.get("ARGUS_RUNTIME", "").strip()
        if explicit:
            rt = self._create_explicit(explicit)
            if rt is not None:
                self._cached_runtime = rt
                return rt
            logger.warning(
                "Requested runtime '%s' is not available. Falling back to auto-detection.",
                explicit,
            )

        for entry in self._registry:
            if entry.detector():
                rt = self._create_from_entry(entry)
                if rt is not None:
                    logger.info(
                        "Auto-detected container runtime: %s (priority %d).",
                        rt.name,
                        entry.priority,
                    )
                    self._cached_runtime = rt
                    return rt

        logger.warning(
            "No container runtime detected (docker/podman/kubernetes).",
        )
        return None

    def _create_explicit(self, name: str) -> Optional[ContainerRuntime]:
        normalised = name.strip().lower()
        if normalised in ("docker", "podman"):
            if shutil.which(normalised):
                return DockerRuntime(binary=normalised)
            return None
        if normalised in ("kubernetes", "k8s", "kube"):
            if KubernetesRuntime.is_available():
                return KubernetesRuntime()
            return None
        return None

    def _create_from_entry(
        self,
        entry: _RuntimeEntry,
    ) -> Optional[ContainerRuntime]:
        if entry.runtime_cls is DockerRuntime:
            if entry.priority == 100 and shutil.which("docker"):
                return DockerRuntime(binary="docker")
            if entry.priority == 110 and shutil.which("podman"):
                return DockerRuntime(binary="podman")
            return None
        if entry.runtime_cls is KubernetesRuntime:
            return KubernetesRuntime()
        return None


# Used by existing callers.  Delegate to the factory / DockerRuntime.


def detect_runtime() -> Optional[str]:
    """Detect a supported container runtime on ``$PATH``.

    Returns ``"docker"``, ``"podman"``, or ``None``.
    Docker is preferred when both are available.

    .. deprecated::
        Use :meth:`RuntimeFactory.get().detect()` instead.
    """
    for binary in ("docker", "podman"):
        if shutil.which(binary):
            return binary
    return None


async def check_runtime_health(runtime: str) -> bool:
    """Quick health probe — can the daemon respond within timeout?

    .. deprecated::
        Use :meth:`ContainerRuntime.is_healthy` instead.
    """
    rt = DockerRuntime(binary=runtime)
    return await rt.is_healthy()


async def image_exists(runtime: str, image_tag: str) -> bool:
    """Check whether *image_tag* exists locally.

    .. deprecated::
        Use :meth:`ContainerRuntime.image_exists` instead.
    """
    rt = DockerRuntime(binary=runtime)
    return await rt.image_exists(image_tag)


async def pull_image(runtime: str, image: str) -> bool:
    """Pull *image* from a remote registry.

    .. deprecated::
        Use :meth:`ContainerRuntime.pull_image` instead.
    """
    rt = DockerRuntime(binary=runtime)
    return await rt.pull_image(image)


async def build_image(
    runtime: str,
    context_dir: str,
    image_tag: str,
    *,
    dockerfile: str = "Dockerfile",
    line_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """Build a container image.

    .. deprecated::
        Use :meth:`ContainerRuntime.build_image` instead.
    """
    rt = DockerRuntime(binary=runtime)
    return await rt.build_image(
        context_dir,
        image_tag,
        dockerfile=dockerfile,
        line_callback=line_callback,
    )


async def remove_image(runtime: str, image_tag: str) -> None:
    """Remove a local image (best-effort).

    .. deprecated::
        Use :meth:`ContainerRuntime.remove_image` instead.
    """
    rt = DockerRuntime(binary=runtime)
    await rt.remove_image(image_tag)
