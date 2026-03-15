"""Tests for argus_mcp.errors — Custom exception classes.

Covers:
- ArgusBaseError hierarchy
- BackendServerError message formatting (with/without server name, original exception)
- CapabilityConflictError message formatting
- ConfigurationError instantiation
- Exception inheritance chain
"""

from __future__ import annotations

import pytest

from argus_mcp.errors import (
    ArgusBaseError,
    BackendServerError,
    CapabilityConflictError,
    ConfigurationError,
)


class TestArgusBaseError:
    """ArgusBaseError is the root of the custom exception hierarchy."""

    def test_is_exception(self) -> None:
        assert issubclass(ArgusBaseError, Exception)

    def test_instantiation(self) -> None:
        err = ArgusBaseError("base error")
        assert str(err) == "base error"

    def test_catchable_as_exception(self) -> None:
        with pytest.raises(Exception):
            raise ArgusBaseError("test")


class TestConfigurationError:
    def test_inherits_argus_base(self) -> None:
        assert issubclass(ConfigurationError, ArgusBaseError)

    def test_message(self) -> None:
        err = ConfigurationError("bad config")
        assert "bad config" in str(err)

    def test_catchable_as_argus_base(self) -> None:
        with pytest.raises(ArgusBaseError):
            raise ConfigurationError("test")


class TestBackendServerError:
    def test_basic_message(self) -> None:
        err = BackendServerError("connection failed")
        assert "Backend server error" in str(err)
        assert "connection failed" in str(err)

    def test_with_server_name(self) -> None:
        err = BackendServerError("timeout", svr_name="my-backend")
        msg = str(err)
        assert "my-backend" in msg
        assert "timeout" in msg

    def test_with_original_exception(self) -> None:
        orig = TimeoutError("network issue")
        err = BackendServerError("failed", orig_exc=orig)
        msg = str(err)
        assert "TimeoutError" in msg
        assert "failed" in msg

    def test_with_all_fields(self) -> None:
        orig = ConnectionError("refused")
        err = BackendServerError("connect error", svr_name="backend-1", orig_exc=orig)
        msg = str(err)
        assert "backend-1" in msg
        assert "connect error" in msg
        assert "ConnectionError" in msg

    def test_attributes_stored(self) -> None:
        orig = ValueError("bad")
        err = BackendServerError("msg", svr_name="s1", orig_exc=orig)
        assert err.svr_name == "s1"
        assert err.orig_exc is orig

    def test_no_server_name(self) -> None:
        err = BackendServerError("msg", svr_name=None)
        assert "server:" not in str(err)

    def test_no_orig_exc(self) -> None:
        err = BackendServerError("msg", orig_exc=None)
        assert "original error" not in str(err)

    def test_inherits_argus_base(self) -> None:
        assert issubclass(BackendServerError, ArgusBaseError)


class TestCapabilityConflictError:
    def test_message_format(self) -> None:
        err = CapabilityConflictError("search", "server-a", "server-b")
        msg = str(err)
        assert "search" in msg
        assert "server-a" in msg
        assert "server-b" in msg

    def test_inherits_argus_base(self) -> None:
        assert issubclass(CapabilityConflictError, ArgusBaseError)

    def test_mentions_resolution_hint(self) -> None:
        err = CapabilityConflictError("tool", "s1", "s2")
        msg = str(err)
        assert "conflict" in msg.lower()
        # Should mention resolution suggestion
        assert "resolution" in msg.lower() or "unique" in msg.lower()
