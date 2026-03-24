"""Tests for argus_mcp.display.logging_config — secret redaction and log setup.

Covers:
- SecretRedactionFilter: register(), filter(), redaction behaviour
- BASE_LOG_CFG structure validation
- setup_logging() basics
"""

from __future__ import annotations

import logging
import os
import shutil

import pytest

from argus_mcp.display.logging_config import (
    BASE_LOG_CFG,
    SecretRedactionFilter,
    secret_redaction_filter,
    setup_logging,
)

# SecretRedactionFilter


class TestSecretRedactionFilter:
    def test_fresh_instance(self):
        f = SecretRedactionFilter()
        assert f._secrets == set()

    def test_register_adds_secret(self):
        f = SecretRedactionFilter()
        f.register("my-secret-token")
        assert "my-secret-token" in f._secrets

    def test_register_ignores_empty(self):
        f = SecretRedactionFilter()
        f.register("")
        f.register(None)  # type: ignore[arg-type]
        assert len(f._secrets) == 0

    def test_register_ignores_short(self):
        """Secrets shorter than 4 chars are not worth redacting."""
        f = SecretRedactionFilter()
        f.register("abc")
        assert "abc" not in f._secrets

    def test_filter_redacts_in_message(self):
        f = SecretRedactionFilter()
        f.register("super-secret")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Token is super-secret here",
            args=(),
            exc_info=None,
        )
        result = f.filter(record)
        assert result is True  # filter allows record through
        assert "super-secret" not in record.getMessage()
        assert "***REDACTED***" in record.getMessage()

    def test_filter_no_redaction_needed(self):
        f = SecretRedactionFilter()
        f.register("my-secret")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="This message has no secrets",
            args=(),
            exc_info=None,
        )
        f.filter(record)
        assert record.getMessage() == "This message has no secrets"

    def test_filter_multiple_secrets(self):
        f = SecretRedactionFilter()
        f.register("secret-one")
        f.register("secret-two")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="First: secret-one and second: secret-two",
            args=(),
            exc_info=None,
        )
        f.filter(record)
        msg = record.getMessage()
        assert "secret-one" not in msg
        assert "secret-two" not in msg

    def test_singleton_filter_exists(self):
        assert isinstance(secret_redaction_filter, SecretRedactionFilter)


# BASE_LOG_CFG


class TestBaseLogCfg:
    def test_is_dict(self):
        assert isinstance(BASE_LOG_CFG, dict)

    def test_has_version(self):
        assert BASE_LOG_CFG.get("version") == 1

    def test_has_formatters(self):
        assert "formatters" in BASE_LOG_CFG
        assert "simple_file" in BASE_LOG_CFG["formatters"]

    def test_has_handlers(self):
        assert "handlers" in BASE_LOG_CFG
        assert "file_handler" in BASE_LOG_CFG["handlers"]

    def test_file_handler_configured(self):
        fh = BASE_LOG_CFG["handlers"]["file_handler"]
        assert fh["class"] == "logging.FileHandler"
        assert "formatter" in fh

    def test_has_loggers(self):
        loggers = BASE_LOG_CFG.get("loggers", {})
        expected_logger_names = {"uvicorn", "uvicorn.error", "uvicorn.access", "starlette"}
        for name in expected_logger_names:
            assert name in loggers, f"Missing logger config for {name}"

    def test_has_root_logger(self):
        assert "root" in BASE_LOG_CFG
        assert "level" in BASE_LOG_CFG["root"]


# setup_logging


class TestSetupLogging:
    @pytest.fixture(autouse=True)
    def _clean_logs(self, tmp_path, monkeypatch):
        """Redirect LOG_DIR to tmp_path to avoid polluting workspace."""
        log_dir = str(tmp_path / "logs")
        monkeypatch.setattr("argus_mcp.display.logging_config.LOG_DIR", log_dir)
        yield
        # Cleanup
        if os.path.exists(log_dir):
            shutil.rmtree(log_dir, ignore_errors=True)

    def test_returns_tuple(self):
        result = setup_logging("INFO", quiet=True)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_valid_log_level(self):
        log_fpath, lvl = setup_logging("DEBUG", quiet=True)
        assert lvl == "DEBUG"
        assert "DEBUG" in log_fpath

    def test_invalid_log_level_falls_back(self):
        _, lvl = setup_logging("INVALID_LEVEL", quiet=True)
        assert lvl == "INFO"

    def test_log_file_created(self, tmp_path):
        log_fpath, _ = setup_logging("INFO", quiet=True)
        assert os.path.exists(log_fpath)

    def test_quiet_mode_no_stdout(self, capsys):
        setup_logging("INFO", quiet=True)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_non_quiet_prints(self, capsys):
        setup_logging("INFO", quiet=False)
        captured = capsys.readouterr()
        assert "Logging initialized" in captured.out
