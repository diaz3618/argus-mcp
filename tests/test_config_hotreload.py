"""Tests for config diff and watcher"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Dict
from unittest.mock import AsyncMock

from argus_mcp.config.diff import ConfigDiff, compute_diff, configs_differ
from argus_mcp.config.watcher import ConfigWatcher

# ConfigDiff tests


class TestConfigsDiffer:
    def test_same_configs(self) -> None:
        old = {"type": "sse", "url": "http://a.com/sse"}
        new = {"type": "sse", "url": "http://a.com/sse"}
        assert not configs_differ(old, new)

    def test_different_type(self) -> None:
        assert configs_differ({"type": "sse"}, {"type": "stdio"})

    def test_sse_url_changed(self) -> None:
        old = {"type": "sse", "url": "http://a.com/sse"}
        new = {"type": "sse", "url": "http://b.com/sse"}
        assert configs_differ(old, new)

    def test_sse_headers_changed(self) -> None:
        old = {"type": "sse", "url": "http://a.com/sse", "headers": {"X": "1"}}
        new = {"type": "sse", "url": "http://a.com/sse", "headers": {"X": "2"}}
        assert configs_differ(old, new)

    def test_sse_auth_changed(self) -> None:
        old = {"type": "sse", "url": "http://a.com/sse", "auth": None}
        new = {"type": "sse", "url": "http://a.com/sse", "auth": {"type": "static"}}
        assert configs_differ(old, new)

    def test_streamable_http_url_changed(self) -> None:
        old = {"type": "streamable-http", "url": "http://a.com/mcp"}
        new = {"type": "streamable-http", "url": "http://b.com/mcp"}
        assert configs_differ(old, new)

    def test_streamable_http_same(self) -> None:
        cfg = {"type": "streamable-http", "url": "http://a.com/mcp", "headers": None, "auth": None}
        assert not configs_differ(cfg, dict(cfg))

    def test_stdio_params_differ(self) -> None:
        class FakeParams:
            def __init__(self, cmd: str):
                self.command = cmd
                self.args = []
                self.env = None

        old = {"type": "stdio", "params": FakeParams("python")}
        new = {"type": "stdio", "params": FakeParams("node")}
        assert configs_differ(old, new)

    def test_stdio_params_none(self) -> None:
        old = {"type": "stdio", "params": None}
        new = {"type": "stdio", "params": None}
        assert not configs_differ(old, new)


class TestComputeDiff:
    def test_no_changes(self) -> None:
        cfg = {"a": {"type": "sse", "url": "http://x"}}
        diff = compute_diff(cfg, dict(cfg))
        assert not diff.has_changes

    def test_added(self) -> None:
        old: Dict[str, Dict[str, Any]] = {}
        new = {"a": {"type": "sse", "url": "http://x"}}
        diff = compute_diff(old, new)
        assert diff.added == {"a"}
        assert diff.has_changes

    def test_removed(self) -> None:
        old = {"a": {"type": "sse", "url": "http://x"}}
        new: Dict[str, Dict[str, Any]] = {}
        diff = compute_diff(old, new)
        assert diff.removed == {"a"}

    def test_changed(self) -> None:
        old = {"a": {"type": "sse", "url": "http://x"}}
        new = {"a": {"type": "sse", "url": "http://y"}}
        diff = compute_diff(old, new)
        assert diff.changed == {"a"}
        assert not diff.added
        assert not diff.removed

    def test_combined(self) -> None:
        old = {
            "keep": {"type": "sse", "url": "http://x"},
            "change": {"type": "sse", "url": "http://old"},
            "remove": {"type": "sse", "url": "http://gone"},
        }
        new = {
            "keep": {"type": "sse", "url": "http://x"},
            "change": {"type": "sse", "url": "http://new"},
            "add": {"type": "sse", "url": "http://fresh"},
        }
        diff = compute_diff(old, new)
        assert diff.added == {"add"}
        assert diff.removed == {"remove"}
        assert diff.changed == {"change"}

    def test_summary(self) -> None:
        diff = ConfigDiff(added={"a", "b"}, removed={"c"}, changed=set())
        assert "+2" in diff.summary()
        assert "-1" in diff.summary()


# ConfigWatcher tests


class TestConfigWatcher:
    def test_detects_file_change(self) -> None:
        callback = AsyncMock()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"version":"1"}')
            path = f.name

        try:
            watcher = ConfigWatcher(
                path,
                callback,
                poll_interval=0.1,
                debounce=0.1,
            )

            loop = asyncio.new_event_loop()

            async def run() -> None:
                watcher.start()
                assert watcher.watching
                # Modify the file
                await asyncio.sleep(0.15)
                with open(path, "w") as fw:
                    fw.write('{"version":"1","server":{}}')
                # Wait for poll + debounce
                await asyncio.sleep(0.5)
                await watcher.stop()

            loop.run_until_complete(run())
            loop.close()

            assert callback.call_count >= 1
        finally:
            os.unlink(path)

    def test_no_change_no_callback(self) -> None:
        callback = AsyncMock()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"version":"1"}')
            path = f.name

        try:
            watcher = ConfigWatcher(
                path,
                callback,
                poll_interval=0.1,
                debounce=0.1,
            )

            loop = asyncio.new_event_loop()

            async def run() -> None:
                watcher.start()
                await asyncio.sleep(0.4)
                await watcher.stop()

            loop.run_until_complete(run())
            loop.close()

            callback.assert_not_called()
        finally:
            os.unlink(path)

    def test_stop_is_idempotent(self) -> None:
        callback = AsyncMock()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            path = f.name

        try:
            watcher = ConfigWatcher(path, callback, poll_interval=0.1, debounce=0.1)
            loop = asyncio.new_event_loop()

            async def run() -> None:
                watcher.start()
                await watcher.stop()
                await watcher.stop()  # should not raise
                assert not watcher.watching

            loop.run_until_complete(run())
            loop.close()
        finally:
            os.unlink(path)
