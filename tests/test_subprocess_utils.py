"""Tests for argus_mcp.bridge.subprocess_utils — subprocess lifecycle helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.bridge.subprocess_utils import (
    cancel_stream_loggers,
    log_backend_fail,
    log_subproc_stream,
    manage_subproc,
    terminate_subproc,
)
from argus_mcp.errors import ConfigurationError

# log_subproc_stream ──────────────────────────────────────────────────


class TestLogSubprocStream:
    """Unit tests for stream reading and logging."""

    @pytest.mark.asyncio
    async def test_none_stream_returns_immediately(self) -> None:
        await log_subproc_stream(None, "srv", "stdout")

    @pytest.mark.asyncio
    async def test_reads_until_eof(self) -> None:
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readline = AsyncMock(
            side_effect=[b"line 1\n", b"line 2\n", b""]  # EOF
        )
        await log_subproc_stream(reader, "srv", "stdout")
        assert reader.readline.call_count == 3


# cancel_stream_loggers ──────────────────────────────────────────────


class TestCancelStreamLoggers:
    """Unit tests for cancelling logging tasks."""

    @pytest.mark.asyncio
    async def test_none_tasks_noop(self) -> None:
        await cancel_stream_loggers("srv", None, None)

    @pytest.mark.asyncio
    async def test_cancels_running_tasks(self) -> None:
        out_task = MagicMock()
        out_task.done.return_value = False
        err_task = MagicMock()
        err_task.done.return_value = False

        with patch("asyncio.gather", new_callable=AsyncMock):
            await cancel_stream_loggers("srv", out_task, err_task)
            out_task.cancel.assert_called_once()
            err_task.cancel.assert_called_once()


# terminate_subproc ───────────────────────────────────────────────────


class TestTerminateSubproc:
    """Unit tests for subprocess termination logic."""

    @pytest.mark.asyncio
    async def test_graceful_terminate(self) -> None:
        proc = AsyncMock()
        proc.pid = 1234
        proc.returncode = None
        proc.terminate = MagicMock()
        proc.wait = AsyncMock(return_value=0)

        await terminate_subproc("srv", proc)
        proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_force_kill_on_timeout(self) -> None:
        proc = MagicMock()
        proc.pid = 5678
        proc.returncode = None
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        # wait() must be a coroutine for asyncio.wait_for
        wait_future: asyncio.Future[int] = asyncio.get_event_loop().create_future()
        wait_future.set_result(0)
        proc.wait = MagicMock(return_value=wait_future)

        with patch(
            "argus_mcp.bridge.subprocess_utils.asyncio.wait_for",
            side_effect=asyncio.TimeoutError(),
        ):
            await terminate_subproc("srv", proc)
            proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_lookup_error(self) -> None:
        proc = AsyncMock()
        proc.pid = 9999
        proc.terminate = MagicMock(side_effect=ProcessLookupError())

        await terminate_subproc("srv", proc)
        # Should not raise


# log_backend_fail ────────────────────────────────────────────────────


class TestLogBackendFail:
    """Unit tests for failure logging helper."""

    def test_timeout_error(self) -> None:
        log_backend_fail("srv", "sse", asyncio.TimeoutError(), "startup")

    def test_configuration_error(self) -> None:
        log_backend_fail("srv", "stdio", ConfigurationError("bad"), "startup")

    def test_generic_error(self) -> None:
        log_backend_fail("srv", None, RuntimeError("boom"), "connect")

    def test_connection_error(self) -> None:
        log_backend_fail("srv", "sse", ConnectionRefusedError(), "startup")


# manage_subproc ──────────────────────────────────────────────────────


class TestManageSubproc:
    """Unit tests for the subprocess context manager."""

    @pytest.mark.asyncio
    async def test_file_not_found_raises(self) -> None:
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("no such command"),
        ):
            with pytest.raises(FileNotFoundError):
                async with manage_subproc("nosuchcmd", [], None, "srv"):
                    pass

    @pytest.mark.asyncio
    async def test_successful_lifecycle(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.pid = 42
        mock_proc.returncode = None
        mock_proc.stdout = None
        mock_proc.stderr = None

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            async with manage_subproc("echo", ["hi"], None, "srv") as proc:
                assert proc.pid == 42

    @pytest.mark.asyncio
    async def test_python_command_resolution(self) -> None:
        """'python' command resolves to sys.executable."""
        mock_proc = AsyncMock()
        mock_proc.pid = 10
        mock_proc.returncode = None
        mock_proc.stdout = None
        mock_proc.stderr = None

        with patch(
            "asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec:
            async with manage_subproc("python", [], None, "srv"):
                pass
            # The first argument should be sys.executable, not "python"
            call_args = mock_exec.call_args
            assert call_args[0][0] != "python"
