"""Tests for the Go Docker adapter Python wrapper (build + create)."""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from argus_mcp.bridge.container.go_docker_adapter import GoDockerAdapter, is_available


def _make_adapter_with_mock_call(
    responses: list[Dict[str, Any]],
) -> tuple[GoDockerAdapter, AsyncMock]:
    """Return an adapter whose ``_call`` method returns *responses* in order."""
    adapter = GoDockerAdapter()
    mock = AsyncMock(side_effect=responses)
    adapter._call = mock  # type: ignore[assignment]
    return adapter, mock


# is_available


class TestIsAvailable:
    def test_returns_bool(self):
        result = is_available()
        assert isinstance(result, bool)

    @patch("argus_mcp.bridge.container.go_docker_adapter._find_go_binary", return_value=None)
    def test_false_when_binary_missing(self, _mock):
        assert is_available() is False

    @patch(
        "argus_mcp.bridge.container.go_docker_adapter._find_go_binary",
        return_value="/usr/bin/docker-adapter",
    )
    def test_true_when_binary_found(self, _mock):
        assert is_available() is True


# build()


class TestBuild:
    @pytest.mark.asyncio
    async def test_build_success(self):
        adapter, mock = _make_adapter_with_mock_call(
            [
                {"ok": True, "data": {"image_tag": "test:v1", "status": "built"}},
            ]
        )
        result = await adapter.build("FROM alpine", "test:v1")
        assert result is True
        mock.assert_called_once_with(
            "build",
            {
                "dockerfile_content": "FROM alpine",
                "image_tag": "test:v1",
            },
        )

    @pytest.mark.asyncio
    async def test_build_with_build_args(self):
        adapter, mock = _make_adapter_with_mock_call(
            [
                {"ok": True, "data": {"image_tag": "img:v1", "status": "done"}},
            ]
        )
        result = await adapter.build(
            "FROM node",
            "img:v1",
            build_args={"NODE_VERSION": "22"},
        )
        assert result is True
        call_args = mock.call_args[0]
        assert call_args[0] == "build"
        sent_args = call_args[1]
        assert json.loads(sent_args["build_args"]) == {"NODE_VERSION": "22"}

    @pytest.mark.asyncio
    async def test_build_failure_returns_false(self):
        adapter, _ = _make_adapter_with_mock_call(
            [
                {"ok": False, "error": "build failed: context deadline exceeded"},
            ]
        )
        result = await adapter.build("FROM bad", "bad:v1")
        assert result is False

    @pytest.mark.asyncio
    async def test_build_empty_response_returns_false(self):
        adapter, _ = _make_adapter_with_mock_call([{}])
        result = await adapter.build("FROM alpine", "test:v1")
        assert result is False

    @pytest.mark.asyncio
    async def test_build_no_build_args_omits_key(self):
        adapter, mock = _make_adapter_with_mock_call(
            [
                {"ok": True, "data": {"image_tag": "t:1", "status": "ok"}},
            ]
        )
        await adapter.build("FROM alpine", "t:1", build_args=None)
        sent = mock.call_args[0][1]
        assert "build_args" not in sent


# create()


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_minimal(self):
        adapter, mock = _make_adapter_with_mock_call(
            [
                {"ok": True, "data": {"container_id": "abc123"}},
            ]
        )
        cid = await adapter.create("img:latest", "my-container")
        assert cid == "abc123"
        call_args = mock.call_args[0]
        assert call_args[0] == "create"
        assert call_args[1]["image"] == "img:latest"
        assert call_args[1]["name"] == "my-container"

    @pytest.mark.asyncio
    async def test_create_full_options(self):
        adapter, mock = _make_adapter_with_mock_call(
            [
                {"ok": True, "data": {"container_id": "xyz789"}},
            ]
        )
        cid = await adapter.create(
            "node:22",
            "test-ctr",
            cmd=["node", "server.js"],
            entrypoint=["/bin/sh", "-c"],
            env={"HOME": "/app", "NODE_ENV": "production"},
            network="my_net",
            memory=536870912,
            cpus=0.5,
            volumes=["/tmp/work:/app"],
            read_only=True,
            cap_drop=["ALL"],
        )
        assert cid == "xyz789"

        sent = mock.call_args[0][1]
        assert json.loads(sent["cmd"]) == ["node", "server.js"]
        assert json.loads(sent["entrypoint"]) == ["/bin/sh", "-c"]
        assert json.loads(sent["env"]) == {"HOME": "/app", "NODE_ENV": "production"}
        assert sent["network"] == "my_net"
        assert sent["memory"] == "536870912"
        assert sent["cpus"] == "0.5"
        assert json.loads(sent["volumes"]) == ["/tmp/work:/app"]
        assert sent["read_only"] == "true"
        assert json.loads(sent["cap_drop"]) == ["ALL"]

    @pytest.mark.asyncio
    async def test_create_failure_returns_none(self):
        adapter, _ = _make_adapter_with_mock_call(
            [
                {"ok": False, "error": "create failed: image not found"},
            ]
        )
        cid = await adapter.create("missing:v1", "ctr")
        assert cid is None

    @pytest.mark.asyncio
    async def test_create_empty_data_returns_none(self):
        adapter, _ = _make_adapter_with_mock_call(
            [
                {"ok": True, "data": "unexpected_string"},
            ]
        )
        cid = await adapter.create("img:v1", "ctr")
        assert cid is None

    @pytest.mark.asyncio
    async def test_create_omits_optional_keys_when_defaults(self):
        adapter, mock = _make_adapter_with_mock_call(
            [
                {"ok": True, "data": {"container_id": "id1"}},
            ]
        )
        await adapter.create("img:v1", "c1")
        sent = mock.call_args[0][1]
        # Only image and name should be present when everything else is default.
        assert set(sent.keys()) == {"image", "name"}


# _parse_memory_string (in wrapper module)


class TestParseMemoryString:
    """Tests for the ``_parse_memory_string`` helper in wrapper.py."""

    @pytest.fixture(autouse=True)
    def _import_helper(self):
        from argus_mcp.bridge.container.wrapper import _parse_memory_string

        self._parse = _parse_memory_string

    def test_plain_int(self):
        assert self._parse("536870912") == 536870912

    def test_megabytes(self):
        assert self._parse("512m") == 512 * 1024 * 1024

    def test_gigabytes(self):
        assert self._parse("1g") == 1 * 1024**3

    def test_kilobytes(self):
        assert self._parse("1024k") == 1024 * 1024

    def test_terabytes(self):
        assert self._parse("1t") == 1024**4

    def test_uppercase(self):
        assert self._parse("256M") == 256 * 1024**2

    def test_zero(self):
        assert self._parse("0") == 0

    def test_empty_returns_zero(self):
        assert self._parse("") == 0

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            self._parse("abc")
