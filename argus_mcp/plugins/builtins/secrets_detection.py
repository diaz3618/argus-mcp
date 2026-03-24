"""Secrets-detection plugin — blocks or redacts API keys, tokens, and private keys.

Scans tool arguments and results for patterns that match common secret
formats (AWS keys, JWTs, private keys, generic high-entropy tokens).
In ``enforce`` mode the request is blocked; otherwise the matched values
are redacted in-place.
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar, List, Pattern

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

try:
    from argus_mcp.plugins.builtins_rust import RUST_AVAILABLE as _SEC_RUST
    from argus_mcp.plugins.builtins_rust import RustSecretsScanner as _RustSec
except ImportError:
    _SEC_RUST = False
    _RustSec = None

logger = logging.getLogger(__name__)

_PATTERNS: List[tuple[str, Pattern[str]]] = [
    (
        "AWS Access Key",
        re.compile(r"(?:^|[^A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?:[^A-Za-z0-9]|$)"),
    ),
    (
        "AWS Secret Key",
        re.compile(r"(?:aws_secret_access_key|secret_key)\s*[:=]\s*\S{20,}", re.IGNORECASE),
    ),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("Private Key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub Token", re.compile(r"gh[ps]_[A-Za-z0-9_]{36,}")),
    ("Generic Bearer", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE)),
]

_REDACTION = "***REDACTED***"


class SecretsDetectionPlugin(PluginBase):
    """Scan tool arguments / results for leaked secrets."""

    _patterns: ClassVar[List[tuple[str, Pattern[str]]]] = _PATTERNS

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._block: bool = config.settings.get("block", True)
        self._rust_engine = (
            _RustSec(redaction=_REDACTION) if _SEC_RUST and _RustSec is not None else None
        )

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        self._scan_arguments(ctx)
        return ctx

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        self._scan_result(ctx)
        return ctx

    def _scan_arguments(self, ctx: PluginContext) -> None:
        for key, value in list(ctx.arguments.items()):
            if not isinstance(value, str):
                continue
            if self._rust_engine is not None:
                found = self._rust_engine.scan(value)
                if found:
                    if self._block:
                        msg = f"Blocked: {found[0]} detected in argument '{key}'"
                        ctx.metadata["secrets_blocked"] = True
                        raise ValueError(msg)
                    ctx.arguments[key] = self._rust_engine.redact(value)
                    ctx.metadata["secrets_redacted"] = True
                    logger.info("Redacted %s in argument '%s'.", ", ".join(found), key)
                continue
            for label, pattern in self._patterns:
                if pattern.search(value):
                    if self._block:
                        msg = f"Blocked: {label} detected in argument '{key}'"
                        ctx.metadata["secrets_blocked"] = True
                        raise ValueError(msg)
                    ctx.arguments[key] = pattern.sub(_REDACTION, value)
                    ctx.metadata["secrets_redacted"] = True
                    logger.info("Redacted %s in argument '%s'.", label, key)

    def _scan_result(self, ctx: PluginContext) -> None:
        if not isinstance(ctx.result, str):
            return
        if self._rust_engine is not None:
            if self._rust_engine.has_secrets(ctx.result):
                ctx.result = self._rust_engine.redact(ctx.result)
                ctx.metadata["secrets_redacted_result"] = True
            return
        for label, pattern in self._patterns:
            if pattern.search(ctx.result):
                ctx.result = pattern.sub(_REDACTION, ctx.result)
                ctx.metadata["secrets_redacted_result"] = True
                logger.info("Redacted %s in tool result.", label)
