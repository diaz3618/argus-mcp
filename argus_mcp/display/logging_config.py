"""Logging configuration setup."""

import copy
import logging
import logging.config
import os
import re
import sys
from datetime import datetime
from typing import Any, Set, Tuple  # noqa: UP035

from argus_mcp.constants import LOG_DIR

_REDACTED = "***REDACTED***"


class SecretRedactionFilter(logging.Filter):
    """Logging filter that replaces resolved secret values with a placeholder.

    Call :meth:`register` to add values that should be scrubbed.  Thread-safe
    because CPython's GIL protects set reads against concurrent adds.
    """

    def __init__(self) -> None:
        super().__init__()
        self._secrets: Set[str] = set()
        self._pattern: re.Pattern[str] | None = None

    def register(self, value: str) -> None:
        """Register a secret value for redaction."""
        if value and len(value) >= 4:  # skip trivially short values
            self._secrets.add(value)
            # Rebuild regex pattern with longest-first ordering
            escaped = sorted((re.escape(s) for s in self._secrets), key=len, reverse=True)
            self._pattern = re.compile("|".join(escaped))

    def filter(self, record: logging.LogRecord) -> bool:
        if self._pattern is not None:
            if isinstance(record.msg, str):
                record.msg = self._pattern.sub(_REDACTED, record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: self._pattern.sub(_REDACTED, str(v)) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        self._pattern.sub(_REDACTED, str(a)) if isinstance(a, str) else a
                        for a in record.args
                    )
        return True


# Module-level singleton so resolver can register values at resolve time.
secret_redaction_filter = SecretRedactionFilter()

BASE_LOG_CFG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple_file": {
            "format": ("%(asctime)s - %(name)25s:%(lineno)-4d - %(levelname)-7s - %(message)s"),
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "file_handler": {
            "class": "logging.FileHandler",
            "level": "DEBUG",
            "formatter": "simple_file",
            "filename": "temp_log_name.log",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
        "uvicorn.error": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
        "uvicorn.access": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "WARNING",
        },
        "starlette": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
        "argus_mcp": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
        "argus_mcp.server": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
        "argus_mcp.bridge": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
        "argus_mcp.config": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
        "argus_mcp.display": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
        "mcp": {
            "handlers": ["file_handler"],
            "propagate": False,
            "level": "INFO",
        },
    },
    "root": {
        "handlers": ["file_handler"],
        "level": "WARNING",
    },
}


def setup_logging(log_lvl_str: str, *, quiet: bool = False) -> Tuple[str, str]:
    """
    Set up the logging system.

    Uses a timestamped dynamic filename and adjusts module log levels
    based on command-line arguments.

    Args:
        log_lvl_str: The desired log level string (e.g., 'debug', 'info').
        quiet: If *True*, suppress all ``print()`` output (TUI mode).

    Returns:
        A tuple of (log_file_path, validated_log_level).
    """
    log_lvl_valid = log_lvl_str.upper()
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if log_lvl_valid not in valid_levels:
        if not quiet:
            print(f"Warning: invalid log level '{log_lvl_str}'. Using 'INFO'.")
        log_lvl_valid = "INFO"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(LOG_DIR, exist_ok=True)
    log_fpath = os.path.join(  # nosemgrep: injection-path-traversal-join
        LOG_DIR, f"argus_{ts}_{log_lvl_valid}.log"
    )

    log_cfg: dict[str, Any] = copy.deepcopy(BASE_LOG_CFG)
    log_cfg["handlers"]["file_handler"]["filename"] = log_fpath

    app_loggers_cfg = [
        "argus_mcp",
        "argus_mcp.server",
        "argus_mcp.bridge",
        "argus_mcp.config",
        "argus_mcp.display",
        "mcp",
        "uvicorn",
        "uvicorn.error",
        "starlette",
    ]
    for name in app_loggers_cfg:
        if name in log_cfg["loggers"]:
            log_cfg["loggers"][name]["level"] = log_lvl_valid
        else:
            log_cfg["loggers"][name] = {
                "handlers": ["file_handler"],
                "propagate": False,
                "level": log_lvl_valid,
            }

    log_cfg["loggers"]["uvicorn.access"]["level"] = (
        "INFO" if log_lvl_valid == "DEBUG" else "WARNING"
    )
    log_cfg["root"]["level"] = log_lvl_valid if log_lvl_valid == "DEBUG" else "WARNING"

    try:
        logging.config.dictConfig(log_cfg)
        # Attach secret redaction filter to all handlers
        for handler in logging.root.handlers:
            handler.addFilter(secret_redaction_filter)
        if not quiet:
            print(f"Logging initialized. File log level: {log_lvl_valid}, log file: {log_fpath}")
    except (ValueError, TypeError, AttributeError, OSError) as e_log_cfg:
        if not quiet:
            print(
                f"Error applying logging configuration: {e_log_cfg}",
                file=sys.stderr,
            )

    return log_fpath, log_lvl_valid
