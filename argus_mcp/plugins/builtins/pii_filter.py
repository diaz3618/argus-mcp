"""PII-filter plugin — masks personally identifiable information.

Scans tool arguments and results for common PII patterns (email
addresses, Social Security numbers, credit card numbers, phone numbers,
passport numbers) and replaces matches with masked placeholders.
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar, Dict, List, Pattern

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

try:
    from argus_mcp.plugins.builtins_rust import RUST_AVAILABLE as _PII_RUST
    from argus_mcp.plugins.builtins_rust import RustPiiFilter as _RustPii
except ImportError:
    _PII_RUST = False
    _RustPii = None

logger = logging.getLogger(__name__)

_PII_PATTERNS: List[tuple[str, Pattern[str], str]] = [
    (
        "email",
        re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
        "***EMAIL***",
    ),
    (
        "ssn",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "***SSN***",
    ),
    (
        "credit_card",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        "***CC***",
    ),
    (
        "phone_us",
        re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "***PHONE***",
    ),
    (
        "passport",
        re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),
        "***PASSPORT***",
    ),
]


class PiiFilterPlugin(PluginBase):
    """Mask PII in tool arguments and results."""

    _patterns: ClassVar[List[tuple[str, Pattern[str], str]]] = _PII_PATTERNS

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        # Allow config to override which pattern categories are active
        active: List[str] = config.settings.get("categories", [])
        if active:
            self._active_patterns = [(n, p, m) for n, p, m in self._patterns if n in active]
        else:
            self._active_patterns = list(self._patterns)
        # Use Rust engine when available for faster string scanning
        self._rust_engine = (
            _RustPii(categories=active or None) if _PII_RUST and _RustPii is not None else None
        )

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        counts = self._mask_dict(ctx.arguments)
        if counts:
            ctx.metadata["pii_pre_masked"] = counts
        return ctx

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        if isinstance(ctx.result, str):
            masked, counts = self._mask_string(ctx.result)
            if counts:
                ctx.result = masked
                ctx.metadata["pii_post_masked"] = counts
        return ctx

    def _mask_dict(self, d: Dict[str, object]) -> Dict[str, int]:
        """Mask PII in string values of *d* in-place.  Returns counts."""
        total_counts: Dict[str, int] = {}
        for key in list(d):
            value = d[key]
            if not isinstance(value, str):
                continue
            masked, counts = self._mask_string(value)
            if counts:
                d[key] = masked
                for cat, n in counts.items():
                    total_counts[cat] = total_counts.get(cat, 0) + n
        return total_counts

    def _mask_string(self, text: str) -> tuple[str, Dict[str, int]]:
        """Return ``(masked_text, {category: count})``."""
        if self._rust_engine is not None:
            return self._rust_engine.mask_string(text)
        counts: Dict[str, int] = {}
        for name, pattern, replacement in self._active_patterns:
            new_text, n = pattern.subn(replacement, text)
            if n:
                counts[name] = n
                text = new_text
                logger.debug("PII filter: masked %d %s occurrence(s).", n, name)
        return text, counts
