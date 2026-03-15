"""Tests for the argus_mcp.bridge.container package.

Covers:
- RuntimeType enum + ABC + DockerRuntime + KubernetesRuntime (runtime.py)
- RuntimeFactory auto-detection and explicit override
- Backward-compatible module-level runtime functions
- Dockerfile template generation + arg parsing (templates.py)
- Image builder classification and caching (image_builder.py)
- Network policy + managed network helpers (network.py)
- High-level wrapper (wrapper.py) — enabled/runtime_override flow
- ContainerConfig + StdioBackendConfig defaults (schema_backends.py)
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import StdioServerParameters

# runtime.py: new ABC layer ──────────────────────────────────────────
from argus_mcp.bridge.container.runtime import (
    DockerRuntime,
    KubernetesRuntime,
    RuntimeFactory,
    RuntimeType,
    # Backward-compat module-level functions
    build_image,
    check_runtime_health,
    detect_runtime,
    image_exists,
    pull_image,
)

# RuntimeType enum ───────────────────────────────────────────────────


class TestRuntimeType:
    """RuntimeType.from_str parsing and aliases."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("docker", RuntimeType.DOCKER),
            ("Docker", RuntimeType.DOCKER),
            ("DOCKER", RuntimeType.DOCKER),
            ("podman", RuntimeType.PODMAN),
            ("kubernetes", RuntimeType.KUBERNETES),
            ("k8s", RuntimeType.KUBERNETES),
            ("kube", RuntimeType.KUBERNETES),
            ("  docker  ", RuntimeType.DOCKER),
        ],
    )
    def test_from_str_valid(self, value: str, expected: RuntimeType) -> None:
        assert RuntimeType.from_str(value) is expected

    def test_from_str_invalid(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            RuntimeType.from_str("invalid-runtime")


# DockerRuntime (new ABC implementation) ──────────────────────────────


class TestDockerRuntime:
    """DockerRuntime CLI wrapper tests (subprocess mocked)."""

    def test_name_returns_binary(self) -> None:
        rt = DockerRuntime(binary="docker")
        assert rt.name == "docker"

    def test_runtime_type_docker(self) -> None:
        assert DockerRuntime(binary="docker").runtime_type is RuntimeType.DOCKER

    def test_runtime_type_podman(self) -> None:
        assert DockerRuntime(binary="podman").runtime_type is RuntimeType.PODMAN

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_is_healthy_success(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.wait.return_value = 0
        mock_exec.return_value = proc
        assert await rt.is_healthy() is True

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_is_healthy_caches_result(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.wait.return_value = 0
        mock_exec.return_value = proc
        assert await rt.is_healthy() is True
        assert await rt.is_healthy() is True
        # Only called once — second hit is cached.
        mock_exec.assert_called_once()

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_is_healthy_failure_nonzero_rc(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.wait.return_value = 1
        mock_exec.return_value = proc
        assert await rt.is_healthy() is False

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_is_healthy_timeout(self, mock_exec) -> None:
        """If the daemon hangs, health check should time out."""
        import argus_mcp.bridge.container.runtime as _rt

        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()

        async def _hang():
            await asyncio.sleep(999)

        proc.wait = _hang
        proc.kill = MagicMock()
        mock_exec.return_value = proc

        old_timeout = _rt._HEALTH_CHECK_TIMEOUT
        _rt._HEALTH_CHECK_TIMEOUT = 0.1
        try:
            assert await rt.is_healthy() is False
        finally:
            _rt._HEALTH_CHECK_TIMEOUT = old_timeout

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec", side_effect=OSError("no docker"))
    async def test_is_healthy_exception(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        assert await rt.is_healthy() is False

    def test_reset_health_cache(self) -> None:
        rt = DockerRuntime(binary="docker")
        rt._healthy = True
        rt.reset_health_cache()
        assert rt._healthy is None

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_image_exists_true(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.wait.return_value = 0
        mock_exec.return_value = proc
        assert await rt.image_exists("myimage:latest") is True

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_image_exists_false(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.wait.return_value = 1
        mock_exec.return_value = proc
        assert await rt.image_exists("myimage:latest") is False

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_build_image_success(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.communicate.return_value = (b"Built\n", b"")
        proc.returncode = 0
        mock_exec.return_value = proc
        assert await rt.build_image("/tmp/ctx", "img:v1") is True

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_build_image_failure(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"error\n")
        proc.returncode = 1
        mock_exec.return_value = proc
        assert await rt.build_image("/tmp/ctx", "img:v1") is False

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_pull_image_success(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.communicate.return_value = (b"Done\n", b"")
        proc.returncode = 0
        mock_exec.return_value = proc
        assert await rt.pull_image("alpine:latest") is True

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_pull_image_failure(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"not found\n")
        proc.returncode = 1
        mock_exec.return_value = proc
        assert await rt.pull_image("does-not-exist") is False

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_remove_image(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.wait.return_value = 0
        mock_exec.return_value = proc
        await rt.remove_image("img:v1")  # Should not raise.

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_create_network_already_exists(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.communicate.return_value = (b"some-id", b"")
        proc.returncode = 0
        mock_exec.return_value = proc
        assert await rt.create_network("argus-mcp") is True

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_list_images(self, mock_exec) -> None:
        rt = DockerRuntime(binary="docker")
        proc = AsyncMock()
        proc.communicate.return_value = (
            b"arguslocal/uvx-foo:abc123\narguslocal/npx-bar:def456\n",
            b"",
        )
        proc.returncode = 0
        mock_exec.return_value = proc
        images = await rt.list_images(prefix="arguslocal/")
        assert images == [
            "arguslocal/uvx-foo:abc123",
            "arguslocal/npx-bar:def456",
        ]


# KubernetesRuntime (placeholder) ────────────────────────────────────


class TestKubernetesRuntime:
    """KubernetesRuntime placeholder tests."""

    def test_runtime_type(self) -> None:
        assert KubernetesRuntime().runtime_type is RuntimeType.KUBERNETES

    def test_name(self) -> None:
        assert KubernetesRuntime().name == "kubernetes"

    def test_is_available_without_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert KubernetesRuntime.is_available() is False

    def test_is_available_with_env(self) -> None:
        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}):
            assert KubernetesRuntime.is_available() is True


# RuntimeFactory ──────────────────────────────────────────────────────


class TestRuntimeFactory:
    """Factory auto-detection and explicit override."""

    def setup_method(self) -> None:
        RuntimeFactory.reset()

    def teardown_method(self) -> None:
        RuntimeFactory.reset()

    @patch("shutil.which", side_effect=lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
    def test_detect_docker_on_path(self, mock_which) -> None:
        rt = RuntimeFactory.get().detect()
        assert rt is not None
        assert isinstance(rt, DockerRuntime)
        assert rt.name == "docker"

    @patch("shutil.which", side_effect=lambda cmd: "/usr/bin/podman" if cmd == "podman" else None)
    def test_detect_podman_fallback(self, mock_which) -> None:
        rt = RuntimeFactory.get().detect()
        assert rt is not None
        assert isinstance(rt, DockerRuntime)
        assert rt.name == "podman"

    @patch("shutil.which", return_value=None)
    def test_detect_none_available(self, mock_which) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert RuntimeFactory.get().detect() is None

    @patch("shutil.which", return_value="/usr/bin/podman")
    def test_detect_with_override(self, mock_which) -> None:
        rt = RuntimeFactory.get().detect(override="podman")
        assert rt is not None
        assert rt.name == "podman"

    @patch("shutil.which", return_value="/usr/bin/podman")
    def test_detect_with_env_override(self, mock_which) -> None:
        with patch.dict(os.environ, {"ARGUS_RUNTIME": "podman"}):
            rt = RuntimeFactory.get().detect()
            assert rt is not None
            assert rt.name == "podman"

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_detect_caches_result(self, mock_which) -> None:
        factory = RuntimeFactory.get()
        rt1 = factory.detect()
        rt2 = factory.detect()
        assert rt1 is rt2

    @patch("shutil.which", return_value="/usr/bin/docker")
    def test_reset_clears_cache(self, mock_which) -> None:
        factory = RuntimeFactory.get()
        rt1 = factory.detect()
        RuntimeFactory.reset()
        rt2 = RuntimeFactory.get().detect()
        assert rt1 is not rt2


# Backward-compat module-level functions ──────────────────────────────
#    These delegate to DockerRuntime and still need to work.


class TestDetectRuntime:
    """Tests for detect_runtime() backward-compat wrapper."""

    @patch("shutil.which", side_effect=lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
    def test_finds_docker(self, mock_which):
        assert detect_runtime() == "docker"

    @patch("shutil.which", side_effect=lambda cmd: "/usr/bin/podman" if cmd == "podman" else None)
    def test_finds_podman(self, mock_which):
        assert detect_runtime() == "podman"

    @patch("shutil.which", return_value=None)
    def test_none_when_missing(self, mock_which):
        assert detect_runtime() is None

    @patch("shutil.which", side_effect=lambda cmd: "/usr/bin/" + cmd)
    def test_prefers_docker_over_podman(self, mock_which):
        assert detect_runtime() == "docker"


class TestCheckRuntimeHealth:
    """Tests for check_runtime_health() backward-compat wrapper."""

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_healthy_daemon(self, mock_exec):
        proc = AsyncMock()
        proc.wait.return_value = 0
        mock_exec.return_value = proc
        assert await check_runtime_health("docker") is True

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_unhealthy_daemon_rc_nonzero(self, mock_exec):
        proc = AsyncMock()
        proc.wait.return_value = 1
        mock_exec.return_value = proc
        assert await check_runtime_health("docker") is False

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec", side_effect=OSError("no docker"))
    async def test_exception_returns_false(self, mock_exec):
        assert await check_runtime_health("docker") is False


class TestImageExists:
    """Tests for image_exists() backward-compat wrapper."""

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_returns_true_on_rc0(self, mock_exec):
        proc = AsyncMock()
        proc.wait.return_value = 0
        mock_exec.return_value = proc
        assert await image_exists("docker", "myimage:latest") is True
        mock_exec.assert_called_once()

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_returns_false_on_rc1(self, mock_exec):
        proc = AsyncMock()
        proc.wait.return_value = 1
        mock_exec.return_value = proc
        assert await image_exists("docker", "myimage:latest") is False


class TestPullImage:
    """Tests for pull_image() backward-compat wrapper."""

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_returns_true_on_success(self, mock_exec):
        proc = AsyncMock()
        proc.communicate.return_value = (b"Done\n", b"")
        proc.returncode = 0
        mock_exec.return_value = proc
        assert await pull_image("docker", "python:3.13-slim") is True

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_returns_false_on_failure(self, mock_exec):
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"not found\n")
        proc.returncode = 1
        mock_exec.return_value = proc
        assert await pull_image("docker", "does-not-exist") is False


class TestBuildImage:
    """Tests for build_image() backward-compat wrapper."""

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_build_success(self, mock_exec):
        proc = AsyncMock()
        proc.communicate.return_value = (b"Successfully built\n", b"")
        proc.returncode = 0
        mock_exec.return_value = proc
        assert await build_image("docker", "/tmp/ctx", "myimage:abc") is True
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "docker"
        assert "build" in call_args

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_build_failure(self, mock_exec):
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"build error\n")
        proc.returncode = 1
        mock_exec.return_value = proc
        assert await build_image("docker", "/tmp/ctx", "myimage:abc") is False


# templates.py ────────────────────────────────────────────────────────

from argus_mcp.bridge.container.templates import (
    IMAGE_PREFIX,
    compute_image_tag,
    generate_npx_dockerfile,
    generate_uvx_dockerfile,
    parse_npx_args,
    parse_uvx_args,
)


class TestParseUvxArgs:
    """Tests for parse_uvx_args()."""

    def test_simple_package(self):
        pkg, binary, extra = parse_uvx_args(["mcp-server-fetch"])
        assert pkg == "mcp-server-fetch"
        assert binary == "mcp-server-fetch"
        assert extra == []

    def test_from_flag(self):
        pkg, binary, extra = parse_uvx_args(["--from", "some-package", "some-binary"])
        assert pkg == "some-package"
        assert binary == "some-binary"
        assert extra == []

    def test_from_flag_with_version(self):
        pkg, binary, extra = parse_uvx_args(["--from", "pkg@1.2.3", "mybinary"])
        assert pkg == "pkg@1.2.3"
        assert binary == "mybinary"

    def test_package_with_version(self):
        pkg, binary, extra = parse_uvx_args(["my-tool@2.0"])
        assert pkg == "my-tool@2.0"
        # Binary has version stripped
        assert binary == "my-tool"

    def test_extra_flags_passed_through(self):
        pkg, binary, extra = parse_uvx_args(["mcp-server", "--port", "8080"])
        assert pkg == "mcp-server"
        assert binary == "mcp-server"
        assert extra == ["--port", "8080"]

    def test_empty_args(self):
        pkg, binary, extra = parse_uvx_args([])
        assert pkg == "unknown"
        assert binary == "unknown"
        assert extra == []


class TestParseNpxArgs:
    """Tests for parse_npx_args()."""

    def test_simple_package(self):
        pkg, extra = parse_npx_args(["@modelcontextprotocol/server-fetch"])
        assert pkg == "@modelcontextprotocol/server-fetch"
        assert extra == []

    def test_strips_y_flag(self):
        pkg, extra = parse_npx_args(["-y", "some-pkg"])
        assert pkg == "some-pkg"
        assert extra == []

    def test_strips_yes_flag(self):
        pkg, extra = parse_npx_args(["--yes", "some-pkg"])
        assert pkg == "some-pkg"
        assert extra == []

    def test_with_extra_args(self):
        pkg, extra = parse_npx_args(["-y", "some-pkg", "--stdio"])
        assert pkg == "some-pkg"
        assert extra == ["--stdio"]

    def test_empty_args(self):
        pkg, extra = parse_npx_args([])
        assert pkg == "unknown"
        assert extra == []

    def test_scoped_package(self):
        pkg, extra = parse_npx_args(["-y", "@scope/package@1.0.0", "--verbose"])
        assert pkg == "@scope/package@1.0.0"
        assert extra == ["--verbose"]


class TestGenerateUvxDockerfile:
    """Tests for generate_uvx_dockerfile()."""

    def test_basic_structure(self):
        df = generate_uvx_dockerfile("my-pkg", "my-pkg")
        assert "FROM python:3.13-slim" in df
        assert "pip install" in df
        assert "uv" in df
        assert "uv tool install my-pkg" in df
        assert "nonroot" in df
        assert 'ENTRYPOINT ["my-pkg"]' in df

    def test_with_binary_override(self):
        df = generate_uvx_dockerfile("my-pkg", "my-binary")
        assert 'ENTRYPOINT ["my-binary"]' in df

    def test_no_shell_injection(self):
        """Package names are embedded in RUN — verify no backtick or injected semicolons.

        Note: The Jinja2 template's dependency symlink loop uses legitimate
        shell semicolons (``for bin in ...; do``). We verify the *package name*
        is not used to inject arbitrary commands, not that the template is
        semicolon-free.
        """
        df = generate_uvx_dockerfile("safe-pkg-name", "safe-pkg-name")
        assert "`" not in df
        # Ensure no injection-style semicolons adjacent to the package name
        assert "; rm " not in df
        assert "; echo " not in df
        assert ";rm " not in df
        assert "safe-pkg-name;" not in df


class TestGenerateNpxDockerfile:
    """Tests for generate_npx_dockerfile()."""

    def test_basic_structure(self):
        df = generate_npx_dockerfile("@scope/my-server")
        assert "FROM node:22-alpine" in df
        assert "npm install" in df
        assert "@scope/my-server" in df
        assert "NODE_PATH" in df
        assert "__argus_entry" in df

    def test_binary_discovery(self):
        """Dockerfile includes dynamic binary discovery from package.json."""
        df = generate_npx_dockerfile("@scope/my-server")
        assert "package.json" in df
        assert "ln -sf" in df
        assert "__argus_entry" in df
        # Heuristic bin name is used as fast-path first guess
        assert 'BIN_NAME="my-server"' in df

    def test_no_shell_injection(self):
        df = generate_npx_dockerfile("safe-pkg")
        assert "`" not in df
        assert ";" not in df


class TestComputeImageTag:
    """Tests for compute_image_tag()."""

    def test_deterministic(self):
        df = "FROM python:3.13-slim\nRUN pip install uv"
        tag1 = compute_image_tag("uvx", "my-pkg", df)
        tag2 = compute_image_tag("uvx", "my-pkg", df)
        assert tag1 == tag2

    def test_different_content_different_hash(self):
        tag1 = compute_image_tag("uvx", "my-pkg", "content-a")
        tag2 = compute_image_tag("uvx", "my-pkg", "content-b")
        assert tag1 != tag2

    def test_format(self):
        tag = compute_image_tag("uvx", "my-pkg", "dockerfile-content")
        assert tag.startswith(f"{IMAGE_PREFIX}/")
        assert "uvx-my-pkg:" in tag

    def test_scoped_package(self):
        tag = compute_image_tag("npx", "@scope/pkg", "content")
        # Scoped names should be sanitised (no @, no /)
        assert "@" not in tag.split("/", 1)[1].split(":")[0]


# image_builder.py ────────────────────────────────────────────────────

from argus_mcp.bridge.container.image_builder import (
    classify_command,
    ensure_image,
    is_already_containerised,
)


class TestClassifyCommand:
    """Tests for classify_command()."""

    @pytest.mark.parametrize(
        "cmd,expected",
        [
            ("uvx", "uvx"),
            ("uv", "uvx"),
            ("pipx", "uvx"),
            ("npx", "npx"),
            ("node", "npx"),
            ("tsx", "npx"),
            ("docker", "docker"),
            ("podman", None),
            ("python", "uvx"),
            ("python3", "uvx"),
            ("my-custom-tool", None),
        ],
    )
    def test_classify(self, cmd, expected):
        assert classify_command(cmd) == expected


class TestIsAlreadyContainerised:
    """Tests for is_already_containerised()."""

    def test_docker_run(self):
        assert is_already_containerised("docker", ["run", "-i", "--rm", "image:tag"]) is True

    def test_podman_run(self):
        assert is_already_containerised("podman", ["run", "-i", "image:tag"]) is True

    def test_docker_without_run(self):
        assert is_already_containerised("docker", ["build", "."]) is False

    def test_non_docker_command(self):
        assert is_already_containerised("uvx", ["some-pkg"]) is False

    def test_empty_args(self):
        assert is_already_containerised("docker", []) is False


class TestEnsureImage:
    """Tests for ensure_image() — the orchestrator."""

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=True)
    async def test_reuses_cached_image(self, mock_exists):
        tag, binary, runtime_args = await ensure_image(
            "test-server", "uvx", ["my-tool"], None, "docker"
        )
        assert tag is not None
        assert tag.startswith(IMAGE_PREFIX)
        mock_exists.assert_called_once()

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.build_image", return_value=True)
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_builds_when_not_cached(self, mock_exists, mock_build):
        tag, binary, runtime_args = await ensure_image(
            "test-server", "uvx", ["my-tool"], None, "docker"
        )
        assert tag is not None
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.build_image", return_value=False)
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_returns_none_on_build_failure(self, mock_exists, mock_build):
        tag, binary, runtime_args = await ensure_image(
            "test-server", "uvx", ["my-tool"], None, "docker"
        )
        assert tag is None

    @pytest.mark.asyncio
    async def test_returns_passthrough_for_docker(self):
        """When command is 'docker', ensure_image returns None passthrough."""
        tag, binary, runtime_args = await ensure_image(
            "test-server", "docker", ["run", "myimage"], None, "docker"
        )
        assert tag is None
        assert binary == "docker"

    @pytest.mark.asyncio
    async def test_returns_passthrough_for_unknown(self):
        """When command is unrecognised, returns None passthrough."""
        tag, binary, runtime_args = await ensure_image(
            "test-server", "unknown-binary", ["--flag"], None, "docker"
        )
        assert tag is None
        assert binary == "unknown-binary"

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_uvx_build_if_missing_false(self, mock_exists):
        """When build_if_missing=False and image not cached, falls back."""
        tag, binary, runtime_args = await ensure_image(
            "test-server",
            "uvx",
            ["my-tool"],
            None,
            "docker",
            build_if_missing=False,
        )
        assert tag is None
        assert binary == "uvx"

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=True)
    async def test_npx_reuses_cached(self, mock_exists):
        tag, binary, runtime_args = await ensure_image(
            "test-server", "npx", ["-y", "my-package"], None, "docker"
        )
        assert tag is not None
        mock_exists.assert_called_once()

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.build_image", return_value=True)
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_npx_builds_when_not_cached(self, mock_exists, mock_build):
        tag, binary, runtime_args = await ensure_image(
            "test-server", "npx", ["-y", "my-package"], None, "docker"
        )
        assert tag is not None
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.build_image", return_value=False)
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_npx_returns_none_on_build_failure(self, mock_exists, mock_build):
        tag, binary, runtime_args = await ensure_image(
            "test-server", "npx", ["-y", "my-package"], None, "docker"
        )
        assert tag is None

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_npx_build_if_missing_false(self, mock_exists):
        tag, binary, runtime_args = await ensure_image(
            "test-server",
            "npx",
            ["-y", "my-package"],
            None,
            "docker",
            build_if_missing=False,
        )
        assert tag is None
        assert binary == "npx"

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=True)
    async def test_go_reuses_cached(self, mock_exists):
        tag, binary, runtime_args = await ensure_image(
            "test-server",
            "go",
            ["run", "."],
            None,
            "docker",
            go_package="github.com/example/mcp-server",
        )
        assert tag is not None
        assert binary == "/app/mcp-server"
        mock_exists.assert_called_once()

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.build_image", return_value=True)
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_go_builds_when_not_cached(self, mock_exists, mock_build):
        tag, binary, runtime_args = await ensure_image(
            "test-server",
            "go",
            ["run", "."],
            None,
            "docker",
            go_package="github.com/example/mcp-server",
        )
        assert tag is not None
        assert binary == "/app/mcp-server"
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.build_image", return_value=False)
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_go_returns_none_on_build_failure(self, mock_exists, mock_build):
        tag, binary, runtime_args = await ensure_image(
            "test-server",
            "go",
            ["run", "."],
            None,
            "docker",
            go_package="github.com/example/mcp-server",
        )
        assert tag is None

    @pytest.mark.asyncio
    async def test_go_without_package_returns_none(self):
        """Go transport without go_package should return None."""
        tag, binary, runtime_args = await ensure_image(
            "test-server",
            "go",
            ["run", "."],
            None,
            "docker",
            transport_override="go",
        )
        assert tag is None

    @pytest.mark.asyncio
    @patch("argus_mcp.bridge.container.runtime.image_exists", return_value=False)
    async def test_go_build_if_missing_false(self, mock_exists):
        tag, binary, runtime_args = await ensure_image(
            "test-server",
            "go",
            ["run", "."],
            None,
            "docker",
            go_package="github.com/example/mcp-server",
            build_if_missing=False,
        )
        assert tag is None
        assert binary == "go"


# network.py ──────────────────────────────────────────────────────────

from argus_mcp.bridge.container.network import (
    ARGUS_NETWORK,
    DEFAULT_NETWORK,
    build_network_args,
    effective_network,
    ensure_managed_network,
)


class TestNetworkPolicy:
    """Tests for network.py functions."""

    def test_default_is_bridge(self):
        assert DEFAULT_NETWORK == "bridge"

    def test_argus_network_constant(self):
        assert ARGUS_NETWORK == "argus-mcp"

    def test_effective_network_default(self):
        assert effective_network(None) == "bridge"
        assert effective_network("") == "bridge"

    def test_effective_network_override(self):
        assert effective_network("none") == "none"

    def test_effective_network_custom(self):
        assert effective_network("my-network") == "my-network"

    def test_effective_network_strips_whitespace(self):
        assert effective_network("  host  ") == "host"

    def test_build_network_args(self):
        assert build_network_args("bridge") == ["--network", "bridge"]

    def test_build_network_args_none(self):
        assert build_network_args("none") == ["--network", "none"]

    @pytest.mark.asyncio
    async def test_ensure_managed_network_success(self):
        mock_runtime = MagicMock()
        mock_runtime.create_network = AsyncMock(return_value=True)
        result = await ensure_managed_network(mock_runtime)
        assert result is True
        mock_runtime.create_network.assert_awaited_once_with("argus-mcp")

    @pytest.mark.asyncio
    async def test_ensure_managed_network_failure(self):
        mock_runtime = MagicMock()
        mock_runtime.create_network = AsyncMock(side_effect=RuntimeError("fail"))
        result = await ensure_managed_network(mock_runtime)
        assert result is False


# wrapper.py ──────────────────────────────────────────────────────────

from argus_mcp.bridge.container.wrapper import _active_containers, wrap_backend


class TestWrapBackend:
    """Tests for wrap_backend() — the main entry point.

    wrapper.py uses RuntimeFactory.get().detect(override=...) and
    runtime.is_healthy() — NOT the old module-level helpers.

    Container lifecycle uses ``docker create`` + ``docker start -ai``
    instead of ``docker run``.  Tests mock ``_create_container`` to
    return a predictable container ID and verify the create args.
    """

    _FAKE_CID = "abc123def456789012345678901234567890"

    @pytest.fixture(autouse=True)
    def _reset_health_cache(self):
        """Reset the RuntimeFactory singleton and container tracking between tests."""
        RuntimeFactory.get().reset()
        _active_containers.clear()
        yield
        RuntimeFactory.get().reset()
        _active_containers.clear()

    def _make_runtime(self, healthy: bool = True, name: str = "docker"):
        """Create a mock runtime suitable for factory.detect patching."""
        rt = MagicMock()
        rt.name = name
        rt.is_healthy = AsyncMock(return_value=healthy)
        return rt

    # Disable paths ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_disabled_via_enabled_false(self, monkeypatch):
        """Per-backend enabled=False skips isolation entirely."""
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        wrapped, isolated = await wrap_backend("test", params, enabled=False)
        assert not isolated
        assert wrapped.command == "uvx"

    @pytest.mark.asyncio
    async def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("ARGUS_CONTAINER_ISOLATION", "false")
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        wrapped, isolated = await wrap_backend("test", params)
        assert not isolated
        assert wrapped.command == "uvx"

    # Passthrough paths ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_already_containerised_passthrough(self, monkeypatch):
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        params = StdioServerParameters(
            command="docker",
            args=["run", "-i", "--rm", "myimage:tag"],
        )
        wrapped, isolated = await wrap_backend("test", params)
        assert not isolated
        assert wrapped.command == "docker"

    @pytest.mark.asyncio
    async def test_no_runtime_falls_back(self, monkeypatch):
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        with patch.object(
            RuntimeFactory.get(),
            "detect",
            return_value=None,
        ):
            wrapped, isolated = await wrap_backend("test", params)
        assert not isolated
        assert wrapped.command == "uvx"

    @pytest.mark.asyncio
    async def test_unknown_command_falls_back(self, monkeypatch):
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        params = StdioServerParameters(command="my-custom-tool", args=["--help"])
        mock_rt = self._make_runtime(healthy=True)
        with patch.object(
            RuntimeFactory.get(),
            "detect",
            return_value=mock_rt,
        ):
            wrapped, isolated = await wrap_backend("test", params)
        assert not isolated
        assert wrapped.command == "my-custom-tool"

    @pytest.mark.asyncio
    async def test_runtime_unhealthy_falls_back(self, monkeypatch):
        """If health check fails, fall back to bare subprocess."""
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        mock_rt = self._make_runtime(healthy=False)
        with patch.object(
            RuntimeFactory.get(),
            "detect",
            return_value=mock_rt,
        ):
            wrapped, isolated = await wrap_backend("test", params)
        assert not isolated
        assert wrapped.command == "uvx"

    # Runtime override ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_runtime_override_passed(self, monkeypatch):
        """runtime_override is forwarded to factory.detect(override=...)."""
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        mock_rt = self._make_runtime(healthy=True, name="podman")
        factory = RuntimeFactory.get()
        detect_mock = MagicMock(return_value=mock_rt)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        with (
            patch.object(factory, "detect", detect_mock),
            patch(
                "argus_mcp.bridge.container.wrapper.ensure_image",
                return_value=("arguslocal/uvx-my-tool:abc123", None, []),
            ),
            patch(
                "argus_mcp.bridge.container.wrapper._create_container",
                new_callable=AsyncMock,
                return_value=self._FAKE_CID,
            ),
        ):
            wrapped, isolated = await wrap_backend(
                "test",
                params,
                runtime_override="podman",
            )
        detect_mock.assert_called_once_with(override="podman")
        assert isolated
        assert wrapped.command == "podman"
        assert wrapped.args == ["start", "-ai", self._FAKE_CID]

    # Health check caching ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_health_check_cached(self, monkeypatch):
        """Runtime.is_healthy() caches inside the runtime instance."""
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        mock_rt = self._make_runtime(healthy=True)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        with (
            patch.object(
                RuntimeFactory.get(),
                "detect",
                return_value=mock_rt,
            ),
            patch(
                "argus_mcp.bridge.container.wrapper.ensure_image",
                return_value=("arguslocal/uvx-my-tool:abc123", None, []),
            ),
            patch(
                "argus_mcp.bridge.container.wrapper._create_container",
                new_callable=AsyncMock,
                return_value=self._FAKE_CID,
            ),
        ):
            await wrap_backend("test-1", params)
            await wrap_backend("test-2", params)
        # is_healthy is called each time (caching is internal to DockerRuntime)
        assert mock_rt.is_healthy.await_count == 2

    # Successful wrap paths ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_successful_wrap_uvx(self, monkeypatch):
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        mock_rt = self._make_runtime(healthy=True)
        params = StdioServerParameters(
            command="uvx",
            args=["my-tool", "--port", "8080"],
            env={"MY_KEY": "val"},
        )
        with (
            patch.object(
                RuntimeFactory.get(),
                "detect",
                return_value=mock_rt,
            ),
            patch(
                "argus_mcp.bridge.container.wrapper.ensure_image",
                return_value=("arguslocal/uvx-my-tool:abc123", None, ["--port", "8080"]),
            ),
            patch(
                "argus_mcp.bridge.container.wrapper._create_container",
                new_callable=AsyncMock,
                return_value=self._FAKE_CID,
            ) as mock_create,
        ):
            wrapped, isolated = await wrap_backend("test", params)

        assert isolated is True
        # Returned params use 'start -ai' for stdio attach
        assert wrapped.command == "docker"
        assert wrapped.args == ["start", "-ai", self._FAKE_CID]
        # No env on the top-level (all inside container via -e at create time)
        assert wrapped.env is None

        # Verify the create args passed to _create_container
        create_args = mock_create.call_args[0][1]
        assert create_args[0] == "create"
        assert "--rm" in create_args
        assert "-i" in create_args
        assert "--init" in create_args
        assert "--read-only" in create_args
        assert "--cap-drop" in create_args
        assert "arguslocal/uvx-my-tool:abc123" in create_args
        # Env vars passed through via -e (HOME and TMPDIR injected before user env)
        e_indices = [i for i, a in enumerate(create_args) if a == "-e"]
        e_values = [create_args[i + 1] for i in e_indices]
        assert "MY_KEY=val" in e_values
        # Universal container env vars injected
        assert any(v.startswith("HOME=") for v in e_values)
        assert any(v.startswith("TMPDIR=") for v in e_values)
        # Security hardening flags
        assert "--security-opt" in create_args
        so_indices = [i for i, a in enumerate(create_args) if a == "--security-opt"]
        so_values = [create_args[i + 1] for i in so_indices]
        assert "no-new-privileges" in so_values
        assert "label=disable" in so_values
        # Container is tracked
        assert "test" in _active_containers

    @pytest.mark.asyncio
    async def test_network_override(self, monkeypatch):
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        mock_rt = self._make_runtime(healthy=True)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        with (
            patch.object(
                RuntimeFactory.get(),
                "detect",
                return_value=mock_rt,
            ),
            patch(
                "argus_mcp.bridge.container.wrapper.ensure_image",
                return_value=("arguslocal/uvx-my-tool:abc123", None, []),
            ),
            patch(
                "argus_mcp.bridge.container.wrapper._create_container",
                new_callable=AsyncMock,
                return_value=self._FAKE_CID,
            ) as mock_create,
        ):
            wrapped, isolated = await wrap_backend("test", params, network="none")

        assert isolated
        # Network is in the create args, not the returned params
        create_args = mock_create.call_args[0][1]
        assert "--network" in create_args
        net_idx = create_args.index("--network")
        assert create_args[net_idx + 1] == "none"

    @pytest.mark.asyncio
    async def test_build_failure_falls_back(self, monkeypatch):
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        mock_rt = self._make_runtime(healthy=True)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        with (
            patch.object(
                RuntimeFactory.get(),
                "detect",
                return_value=mock_rt,
            ),
            patch(
                "argus_mcp.bridge.container.wrapper.ensure_image",
                return_value=(None, None, []),
            ),
        ):
            wrapped, isolated = await wrap_backend("test", params)

        assert not isolated
        assert wrapped.command == "uvx"

    @pytest.mark.asyncio
    async def test_container_create_failure_falls_back(self, monkeypatch):
        """If docker create fails, fall back to bare subprocess."""
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        mock_rt = self._make_runtime(healthy=True)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        with (
            patch.object(
                RuntimeFactory.get(),
                "detect",
                return_value=mock_rt,
            ),
            patch(
                "argus_mcp.bridge.container.wrapper.ensure_image",
                return_value=("arguslocal/uvx-my-tool:abc", None, []),
            ),
            patch(
                "argus_mcp.bridge.container.wrapper._create_container",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            wrapped, isolated = await wrap_backend("test", params)

        assert not isolated
        assert wrapped.command == "uvx"
        assert "test" not in _active_containers

    @pytest.mark.asyncio
    async def test_volumes_and_extra_args(self, monkeypatch):
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        mock_rt = self._make_runtime(healthy=True)
        params = StdioServerParameters(command="npx", args=["-y", "some-pkg"])
        with (
            patch.object(
                RuntimeFactory.get(),
                "detect",
                return_value=mock_rt,
            ),
            patch(
                "argus_mcp.bridge.container.wrapper.ensure_image",
                return_value=("arguslocal/npx-some-pkg:abc", None, []),
            ),
            patch(
                "argus_mcp.bridge.container.wrapper._create_container",
                new_callable=AsyncMock,
                return_value=self._FAKE_CID,
            ) as mock_create,
        ):
            wrapped, isolated = await wrap_backend(
                "test",
                params,
                volumes=["/data:/data:ro"],
                extra_args=["--label", "env=test"],
            )

        assert isolated
        create_args = mock_create.call_args[0][1]
        assert "-v" in create_args
        v_idx = create_args.index("-v")
        assert create_args[v_idx + 1] == "/data:/data:ro"
        assert "--label" in create_args

    @pytest.mark.asyncio
    async def test_memory_cpus_override(self, monkeypatch):
        monkeypatch.delenv("ARGUS_CONTAINER_ISOLATION", raising=False)
        mock_rt = self._make_runtime(healthy=True)
        params = StdioServerParameters(command="uvx", args=["my-tool"])
        with (
            patch.object(
                RuntimeFactory.get(),
                "detect",
                return_value=mock_rt,
            ),
            patch(
                "argus_mcp.bridge.container.wrapper.ensure_image",
                return_value=("arguslocal/uvx-my-tool:abc", None, []),
            ),
            patch(
                "argus_mcp.bridge.container.wrapper._create_container",
                new_callable=AsyncMock,
                return_value=self._FAKE_CID,
            ) as mock_create,
        ):
            wrapped, isolated = await wrap_backend("test", params, memory="1g", cpus="2")

        assert isolated
        create_args = mock_create.call_args[0][1]
        mem_idx = create_args.index("--memory")
        assert create_args[mem_idx + 1] == "1g"
        cpu_idx = create_args.index("--cpus")
        assert create_args[cpu_idx + 1] == "2"


class TestCreateContainer:
    """Tests for _create_container — the docker create subprocess."""

    @pytest.mark.asyncio
    async def test_success(self):
        from argus_mcp.bridge.container.wrapper import _create_container

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=fake_proc,
        ):
            result = await _create_container("docker", ["create", "--rm", "img"])
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_timeout(self):
        from argus_mcp.bridge.container.wrapper import _create_container

        with patch(
            "asyncio.wait_for",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError,
        ):
            result = await _create_container("docker", ["create", "img"], timeout=1.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_os_error(self):
        from argus_mcp.bridge.container.wrapper import _create_container

        with patch(
            "asyncio.wait_for",
            new_callable=AsyncMock,
            side_effect=OSError("not found"),
        ):
            result = await _create_container("docker", ["create", "img"])
        assert result is None

    @pytest.mark.asyncio
    async def test_nonzero_returncode(self):
        from argus_mcp.bridge.container.wrapper import _create_container

        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.communicate = AsyncMock(return_value=(b"", b"error: something\n"))

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=fake_proc,
        ):
            result = await _create_container("docker", ["create", "img"])
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_stdout(self):
        from argus_mcp.bridge.container.wrapper import _create_container

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=fake_proc,
        ):
            result = await _create_container("docker", ["create", "img"])
        assert result is None


class TestCleanupContainer:
    """Tests for cleanup_container and cleanup_all_containers."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        _active_containers.clear()
        yield
        _active_containers.clear()

    @pytest.mark.asyncio
    async def test_cleanup_no_container(self):
        from argus_mcp.bridge.container.wrapper import cleanup_container

        await cleanup_container("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_cleanup_tracked_container(self):
        from argus_mcp.bridge.container.wrapper import cleanup_container

        _active_containers["test-svr"] = ("docker", "abc123def456")

        fake_proc = MagicMock()
        fake_proc.wait = AsyncMock(return_value=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=fake_proc,
        ):
            await cleanup_container("test-svr")
        assert "test-svr" not in _active_containers

    @pytest.mark.asyncio
    async def test_cleanup_handles_exception(self):
        from argus_mcp.bridge.container.wrapper import cleanup_container

        _active_containers["test-svr"] = ("docker", "abc123def456")

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=Exception("fail"),
        ):
            await cleanup_container("test-svr")
        assert "test-svr" not in _active_containers

    @pytest.mark.asyncio
    async def test_cleanup_all(self):
        from argus_mcp.bridge.container.wrapper import cleanup_all_containers

        _active_containers["svr1"] = ("docker", "cid1")
        _active_containers["svr2"] = ("docker", "cid2")

        fake_proc = MagicMock()
        fake_proc.wait = AsyncMock(return_value=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=fake_proc,
        ):
            await cleanup_all_containers()
        assert len(_active_containers) == 0

    @pytest.mark.asyncio
    async def test_container_cleanup_context(self):
        from argus_mcp.bridge.container.wrapper import container_cleanup_context

        _active_containers["ctx-svr"] = ("docker", "cid-ctx")

        fake_proc = MagicMock()
        fake_proc.wait = AsyncMock(return_value=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=fake_proc,
        ):
            async with container_cleanup_context("ctx-svr"):
                assert "ctx-svr" in _active_containers
        assert "ctx-svr" not in _active_containers


# schema_backends.py ContainerConfig ──────────────────────────────────

from argus_mcp.config.schema_backends import ContainerConfig, StdioBackendConfig


class TestContainerConfig:
    """Tests for the ContainerConfig Pydantic model."""

    def test_enabled_true_by_default(self):
        cfg = ContainerConfig()
        assert cfg.enabled is True

    def test_runtime_none_by_default(self):
        cfg = ContainerConfig()
        assert cfg.runtime is None

    def test_defaults_are_none(self):
        cfg = ContainerConfig()
        assert cfg.network is None
        assert cfg.memory is None
        assert cfg.cpus is None
        assert cfg.volumes == []
        assert cfg.extra_args == []

    def test_enabled_false(self):
        cfg = ContainerConfig(enabled=False)
        assert cfg.enabled is False

    def test_runtime_docker(self):
        cfg = ContainerConfig(runtime="docker")
        assert cfg.runtime == "docker"

    def test_runtime_podman(self):
        cfg = ContainerConfig(runtime="podman")
        assert cfg.runtime == "podman"

    def test_runtime_kubernetes(self):
        cfg = ContainerConfig(runtime="kubernetes")
        assert cfg.runtime == "kubernetes"

    def test_override_values(self):
        cfg = ContainerConfig(
            network="none",
            memory="1g",
            cpus="2",
            volumes=["/data:/data:ro"],
            extra_args=["--label", "x=y"],
        )
        assert cfg.network == "none"
        assert cfg.memory == "1g"
        assert cfg.cpus == "2"
        assert cfg.volumes == ["/data:/data:ro"]

    def test_network_strips_whitespace(self):
        cfg = ContainerConfig(network="  bridge  ")
        assert cfg.network == "bridge"


class TestStdioBackendConfigContainer:
    """Tests for the container field on StdioBackendConfig.

    Container isolation is now on by default: every StdioBackendConfig
    gets a ContainerConfig(enabled=True) unless explicitly overridden.
    """

    def test_default_container_enabled(self):
        """Default container config exists and is enabled."""
        cfg = StdioBackendConfig(type="stdio", command="uvx", args=["my-tool"])
        assert cfg.container is not None
        assert cfg.container.enabled is True
        assert cfg.container.runtime is None

    def test_container_null_coerced_to_defaults(self):
        """YAML `container: null` is coerced to ContainerConfig() by validator."""
        cfg = StdioBackendConfig.model_validate(
            {
                "type": "stdio",
                "command": "uvx",
                "args": ["my-tool"],
                "container": None,
            }
        )
        assert cfg.container is not None
        assert cfg.container.enabled is True

    def test_container_disable_explicit(self):
        """Per-backend opt-out: container: {enabled: false}."""
        cfg = StdioBackendConfig.model_validate(
            {
                "type": "stdio",
                "command": "uvx",
                "args": ["my-tool"],
                "container": {"enabled": False},
            }
        )
        assert cfg.container is not None
        assert cfg.container.enabled is False

    def test_container_with_runtime_override(self):
        cfg = StdioBackendConfig.model_validate(
            {
                "type": "stdio",
                "command": "uvx",
                "args": ["my-tool"],
                "container": {"runtime": "podman"},
            }
        )
        assert cfg.container.runtime == "podman"
        assert cfg.container.enabled is True

    def test_with_container_overrides(self):
        cfg = StdioBackendConfig(
            type="stdio",
            command="uvx",
            args=["my-tool"],
            container=ContainerConfig(network="none", memory="256m"),
        )
        assert cfg.container is not None
        assert cfg.container.network == "none"
        assert cfg.container.memory == "256m"

    def test_from_dict(self):
        """Simulate YAML-style dict input."""
        cfg = StdioBackendConfig.model_validate(
            {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "some-pkg"],
                "container": {"network": "none"},
            }
        )
        assert cfg.container is not None
        assert cfg.container.network == "none"
