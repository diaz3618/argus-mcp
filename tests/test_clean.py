"""Tests for argus_mcp.cli._clean — container/image/network cleanup."""

from __future__ import annotations

import argparse
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from argus_mcp.cli._clean import (
    _BATCH_SIZE,
    _BATCH_TIMEOUT,
    _INDIVIDUAL_TIMEOUT,
    _batch_remove,
    _clean_images,
    _clean_network,
    _cmd_clean,
    _detect_container_runtime,
    _find_argus_containers,
)


class TestDetectContainerRuntime:
    def test_docker_available(self) -> None:
        with patch("argus_mcp.cli._clean.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert _detect_container_runtime() == "docker"

    def test_podman_fallback(self) -> None:
        def side_effect(cmd, **kwargs):
            if cmd[0] == "docker":
                raise FileNotFoundError
            return MagicMock(returncode=0)

        with patch("argus_mcp.cli._clean.subprocess.run", side_effect=side_effect):
            assert _detect_container_runtime() == "podman"

    def test_neither_available(self) -> None:
        with patch(
            "argus_mcp.cli._clean.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert _detect_container_runtime() == "docker"


class TestBatchRemove:
    def test_success_single_batch(self) -> None:
        """All items removed in one batch."""
        ids = ["img1", "img2", "img3"]
        with patch("argus_mcp.cli._clean.subprocess.run") as mock_run:
            removed, failed = _batch_remove("docker", ["rmi", "-f"], ids, label="image")
        assert removed == 3
        assert failed == 0
        mock_run.assert_called_once_with(
            ["docker", "rmi", "-f", "img1", "img2", "img3"],
            capture_output=True,
            timeout=_BATCH_TIMEOUT,
        )

    def test_multiple_batches(self, capsys: pytest.CaptureFixture[str]) -> None:
        """25 IDs with batch_size=10 → 3 batches, progress reported."""
        ids = [f"img{i}" for i in range(25)]
        with patch("argus_mcp.cli._clean.subprocess.run"):
            removed, failed = _batch_remove(
                "docker",
                ["rmi", "-f"],
                ids,
                label="image",
                batch_size=10,
            )
        assert removed == 25
        assert failed == 0
        output = capsys.readouterr().out
        assert "Progress:" in output

    def test_timeout_progressive_retry(self) -> None:
        """Batch timeout triggers individual retries."""
        ids = ["img1", "img2", "img3"]
        call_count = 0

        def side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 120))
            return MagicMock(returncode=0)

        with patch("argus_mcp.cli._clean.subprocess.run", side_effect=side_effect):
            removed, failed = _batch_remove(
                "docker",
                ["rmi", "-f"],
                ids,
                label="image",
            )
        assert removed == 3
        assert failed == 0
        # 1 batch call + 3 individual calls
        assert call_count == 4

    def test_timeout_partial_failure(self) -> None:
        """Batch timeout + some individual timeouts → partial removal."""
        ids = ["img1", "img2", "img3"]
        call_count = 0

        def side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Batch call times out
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 120))
            if call_count == 3:
                # img2 individual retry times out
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 30))
            return MagicMock(returncode=0)

        with patch("argus_mcp.cli._clean.subprocess.run", side_effect=side_effect):
            removed, failed = _batch_remove(
                "docker",
                ["rmi", "-f"],
                ids,
                label="image",
            )
        assert removed == 2
        assert failed == 1

    def test_empty_ids(self) -> None:
        """No IDs → no subprocess calls."""
        with patch("argus_mcp.cli._clean.subprocess.run") as mock_run:
            removed, failed = _batch_remove("docker", ["rmi", "-f"], [], label="image")
        assert removed == 0
        assert failed == 0
        mock_run.assert_not_called()

    def test_custom_timeouts(self) -> None:
        """Custom batch_timeout and individual_timeout are forwarded."""
        ids = ["img1"]
        with patch("argus_mcp.cli._clean.subprocess.run") as mock_run:
            _batch_remove(
                "docker",
                ["rmi", "-f"],
                ids,
                label="image",
                batch_timeout=200,
                individual_timeout=50,
            )
        mock_run.assert_called_once_with(
            ["docker", "rmi", "-f", "img1"],
            capture_output=True,
            timeout=200,
        )


class TestCmdClean:
    @staticmethod
    def _make_args(
        *, images: bool = False, network: bool = False, all: bool = False
    ) -> argparse.Namespace:
        return argparse.Namespace(images=images, network=network, all=all)

    @patch("argus_mcp.cli._clean._clean_network")
    @patch("argus_mcp.cli._clean._clean_images")
    @patch("argus_mcp.cli._clean._batch_remove", return_value=(3, 0))
    @patch("argus_mcp.cli._clean._find_argus_containers")
    @patch("argus_mcp.cli._clean._detect_container_runtime", return_value="docker")
    def test_cmd_clean_success(
        self,
        mock_runtime: MagicMock,
        mock_find: MagicMock,
        mock_batch: MagicMock,
        mock_images: MagicMock,
        mock_network: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Clean removes all containers."""
        mock_find.return_value = (
            ["c1", "c2", "c3"],
            [
                "c1 name1 arguslocal/foo Up",
                "c2 name2 arguslocal/bar Up",
                "c3 name3 arguslocal/baz Up",
            ],
        )
        _cmd_clean(self._make_args())
        mock_batch.assert_called_once()
        output = capsys.readouterr().out
        assert "3 argus-mcp container(s)" in output
        assert "3 container(s) removed" in output

    @patch("argus_mcp.cli._clean._clean_network")
    @patch("argus_mcp.cli._clean._clean_images")
    @patch("argus_mcp.cli._clean._batch_remove", return_value=(1, 2))
    @patch("argus_mcp.cli._clean._find_argus_containers")
    @patch("argus_mcp.cli._clean._detect_container_runtime", return_value="docker")
    def test_cmd_clean_partial_failure(
        self,
        mock_runtime: MagicMock,
        mock_find: MagicMock,
        mock_batch: MagicMock,
        mock_images: MagicMock,
        mock_network: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Some containers fail, print warning."""
        mock_find.return_value = (["c1", "c2", "c3"], ["line1", "line2", "line3"])
        _cmd_clean(self._make_args())
        output = capsys.readouterr().out
        assert "2 container(s) could not be removed" in output

    @patch("argus_mcp.cli._clean._clean_network")
    @patch("argus_mcp.cli._clean._clean_images")
    @patch("argus_mcp.cli._clean._find_argus_containers")
    @patch("argus_mcp.cli._clean._detect_container_runtime", return_value="docker")
    def test_cmd_clean_empty(
        self,
        mock_runtime: MagicMock,
        mock_find: MagicMock,
        mock_images: MagicMock,
        mock_network: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No containers found → graceful message."""
        mock_find.return_value = ([], [])
        _cmd_clean(self._make_args())
        output = capsys.readouterr().out
        assert "No argus-mcp containers found" in output
        mock_images.assert_not_called()
        mock_network.assert_not_called()

    @patch("argus_mcp.cli._clean._clean_network")
    @patch("argus_mcp.cli._clean._clean_images")
    @patch("argus_mcp.cli._clean._find_argus_containers")
    @patch("argus_mcp.cli._clean._detect_container_runtime", return_value="docker")
    def test_cmd_clean_all_flag(
        self,
        mock_runtime: MagicMock,
        mock_find: MagicMock,
        mock_images: MagicMock,
        mock_network: MagicMock,
    ) -> None:
        """--all flag triggers image and network cleanup."""
        mock_find.return_value = ([], [])
        _cmd_clean(self._make_args(all=True))
        mock_images.assert_called_once()
        mock_network.assert_called_once()


class TestCleanImages:
    @patch("argus_mcp.cli._clean._batch_remove", return_value=(5, 0))
    @patch("argus_mcp.cli._clean.subprocess.run")
    def test_removes_found_images(
        self,
        mock_run: MagicMock,
        mock_batch: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_run.return_value = MagicMock(
            stdout="abc123 arguslocal/foo:latest\ndef456 arguslocal/bar:latest\n"
            "ghi789 arguslocal/baz:v1\nj0k1l2 arguslocal/qux:v2\n"
            "m3n4o5 arguslocal/quux:v3\n",
        )
        _clean_images("docker", "arguslocal")
        mock_batch.assert_called_once()
        args = mock_batch.call_args
        assert args[0][2] == ["abc123", "def456", "ghi789", "j0k1l2", "m3n4o5"]
        output = capsys.readouterr().out
        assert "5 arguslocal image(s)" in output
        assert "5 image(s) removed" in output

    @patch("argus_mcp.cli._clean.subprocess.run")
    def test_no_images_found(
        self,
        mock_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_run.return_value = MagicMock(stdout="")
        _clean_images("docker", "arguslocal")
        output = capsys.readouterr().out
        assert "No arguslocal images found" in output


class TestCleanNetwork:
    @patch("argus_mcp.bridge.container.network.ARGUS_NETWORK", "argus-mcp")
    @patch("argus_mcp.cli._clean.subprocess.run")
    def test_removes_existing_network(
        self,
        mock_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_run.side_effect = [
            MagicMock(stdout="abc123\n"),  # network ls
            MagicMock(returncode=0),  # network rm
        ]
        _clean_network("docker")
        output = capsys.readouterr().out
        assert "Network removed" in output

    @patch("argus_mcp.bridge.container.network.ARGUS_NETWORK", "argus-mcp")
    @patch("argus_mcp.cli._clean.subprocess.run")
    def test_no_network_found(
        self,
        mock_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_run.return_value = MagicMock(stdout="")
        _clean_network("docker")
        output = capsys.readouterr().out
        assert "No 'argus-mcp' network found" in output


class TestFindArgusContainers:
    @patch("argus_mcp.cli._clean.subprocess.run")
    def test_finds_matching_containers(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(stdout="abc123 foo arguslocal/server Up 2 hours\n"),
            MagicMock(
                stdout="abc123 foo arguslocal/server Up 2 hours\ndef456 bar nginx:latest Up\n"
            ),
        ]
        ids, lines = _find_argus_containers("docker", "arguslocal")
        assert ids == ["abc123"]
        assert len(lines) == 1

    @patch("argus_mcp.cli._clean.subprocess.run")
    def test_empty_output(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="")
        ids, lines = _find_argus_containers("docker", "arguslocal")
        assert ids == []
        assert lines == []


class TestConstants:
    def test_batch_size(self) -> None:
        assert _BATCH_SIZE == 10

    def test_batch_timeout(self) -> None:
        assert _BATCH_TIMEOUT == 120

    def test_individual_timeout(self) -> None:
        assert _INDIVIDUAL_TIMEOUT == 30
