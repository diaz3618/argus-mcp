"""Markdown-cleaner plugin — terminal-friendly formatting.

Strips or simplifies Markdown syntax from tool results so that they
render cleanly in plain-text terminals and TUI widgets.

Settings (via ``plugin.settings``):
    strip_images : bool — remove ``![alt](url)`` completely (default True)
    strip_links  : bool — replace ``[text](url)`` with just ``text`` (default True)
    strip_html   : bool — remove HTML tags (default True)
"""

from __future__ import annotations

import logging
import re

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)

# Pre-compiled patterns (order matters).
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"\*(.+?)\*")
_STRIKETHROUGH_RE = re.compile(r"~~(.+?)~~")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HR_RE = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)


class MarkdownCleanerPlugin(PluginBase):
    """Simplifies Markdown in tool results for terminal display."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._strip_images: bool = bool(config.settings.get("strip_images", True))
        self._strip_links: bool = bool(config.settings.get("strip_links", True))
        self._strip_html: bool = bool(config.settings.get("strip_html", True))

    def _clean(self, text: str) -> str:
        """Apply all cleaning passes."""
        if self._strip_images:
            text = _IMAGE_RE.sub(r"\1", text)
        if self._strip_links:
            text = _LINK_RE.sub(r"\1", text)
        if self._strip_html:
            text = _HTML_TAG_RE.sub("", text)

        # Simplify inline formatting.
        text = _HEADING_RE.sub("", text)
        text = _BOLD_RE.sub(r"\1", text)
        text = _ITALIC_RE.sub(r"\1", text)
        text = _STRIKETHROUGH_RE.sub(r"\1", text)
        text = _INLINE_CODE_RE.sub(r"\1", text)
        text = _HR_RE.sub("", text)

        return text

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        if not isinstance(ctx.result, str):
            return ctx

        cleaned = self._clean(ctx.result)
        if cleaned != ctx.result:
            ctx.result = cleaned
            ctx.metadata["markdown_cleaned"] = True
        else:
            ctx.metadata["markdown_cleaned"] = False
        return ctx
