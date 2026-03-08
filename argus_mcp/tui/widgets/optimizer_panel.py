"""Optimizer panel — token savings gauge, meta-tool status, and test search.

Displays statistics about the find_tool/call_tool optimizer when enabled,
including token reduction metrics and a test search interface.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, ProgressBar, Static

from argus_mcp._error_utils import safe_query

logger = logging.getLogger(__name__)


class OptimizerPanel(Widget):
    """Optimizer status and test search widget."""

    DEFAULT_CSS = """
    OptimizerPanel {
        height: auto;
        max-height: 24;
        border: round $accent;
        padding: 0 1;
    }
    #opt-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #opt-status {
        height: 1;
        color: $text-muted;
    }
    #opt-savings-bar {
        height: 3;
        margin: 1 0;
    }
    #opt-meta-tools {
        height: auto;
        max-height: 4;
        padding: 0 1;
        margin-bottom: 1;
    }
    #opt-search-bar {
        height: 3;
        padding: 0 1;
        align: left middle;
    }
    #opt-search-input {
        width: 1fr;
        margin-right: 1;
    }
    #opt-limit-input {
        width: 8;
    }
    #opt-results {
        height: auto;
        max-height: 8;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._enabled: bool = False
        self._total_tools: int = 0
        self._optimized_avg: int = 5
        self._baseline_tokens: int = 0
        self._optimized_tokens: int = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Optimizer[/b] — find_tool / call_tool Meta-Tools", id="opt-title")
            yield Static("Optimizer: ✗ Disabled", id="opt-status")

            yield Static("[b]Token Savings[/b]")
            yield ProgressBar(total=100, show_eta=False, id="opt-savings-bar")
            yield Static("", id="opt-savings-detail")

            yield Static("[b]Meta-Tools Exposed[/b]")
            yield Static(
                "  find_tool(query, limit) — semantic search across catalog\n"
                "  call_tool(name, args)   — dynamic invocation → backend",
                id="opt-meta-tools",
            )

            yield Static("[b]Test Search[/b]")
            with Horizontal(id="opt-search-bar"):
                yield Input(placeholder="Query…", id="opt-search-input")
                yield Input(placeholder="5", id="opt-limit-input", type="integer")
                yield Button("Search", id="btn-opt-search", variant="primary")
            yield DataTable(id="opt-results")

    def on_mount(self) -> None:
        if table := safe_query(self, "#opt-results", DataTable):
            table.add_columns("#", "Tool", "Server", "Score")
            table.cursor_type = "row"
            table.zebra_stripes = True

    def update_optimizer_status(
        self,
        enabled: bool = False,
        total_tools: int = 0,
        baseline_tokens: int = 0,
        optimized_tokens: int = 0,
    ) -> None:
        """Update the optimizer status display."""
        self._enabled = enabled
        self._total_tools = total_tools
        self._baseline_tokens = baseline_tokens
        self._optimized_tokens = optimized_tokens

        status_text = (
            f"Optimizer: [green]✓ Enabled[/green]   Store: SQLite FTS5   Tools: {total_tools}"
            if enabled
            else "Optimizer: [dim]✗ Disabled[/dim]"
        )
        if w := safe_query(self, "#opt-status", Static):
            w.update(status_text)

        # Update savings bar
        if baseline_tokens > 0:
            savings_pct = ((baseline_tokens - optimized_tokens) / baseline_tokens) * 100
            if bar := safe_query(self, "#opt-savings-bar", ProgressBar):
                bar.update(progress=savings_pct)
                detail = (
                    f"  Baseline: {total_tools} tools │ ~{baseline_tokens:,} tokens\n"
                    f"  Optimized: avg {self._optimized_avg} │ ~{optimized_tokens:,} tokens\n"
                    f"  Savings: {savings_pct:.1f}%"
                )
                if dw := safe_query(self, "#opt-savings-detail", Static):
                    dw.update(detail)

    def update_search_results(self, results: List[Dict[str, Any]]) -> None:
        """Populate the test search results table."""
        if table := safe_query(self, "#opt-results", DataTable):
            table.clear()
            for i, r in enumerate(results, 1):
                name = r.get("name", "?")
                server = r.get("backend", r.get("server", "?"))
                score = r.get("score", 0)
                table.add_row(str(i), name, server, f"{score:.2f}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-opt-search":
            self._do_test_search()

    def _do_test_search(self) -> None:
        """Run a test search using the real ToolIndex when available.

        Falls back to substring matching against cached capabilities
        if the optimizer index is not accessible from the app.
        """
        try:
            query = self.query_one("#opt-search-input", Input).value.strip()
            if not query:
                return

            limit = 5
            if lw := safe_query(self, "#opt-limit-input", Input):
                try:
                    limit = int(lw.value)
                except (ValueError, TypeError):
                    pass

            # Prefer the real ToolIndex from the optimizer
            from argus_mcp.server.app import mcp_server

            optimizer_index = getattr(mcp_server, "optimizer_index", None)
            if optimizer_index is not None:
                results = optimizer_index.search(query, limit=limit)
                self.update_search_results(results)
                return

            # Fallback: substring match against cached capabilities
            app = self.app
            caps = getattr(app, "_last_caps", None)
            if caps is None:
                self.app.notify(
                    "No capabilities cached — connect to a server first",
                    severity="warning",
                )
                return

            q = query.lower()
            matches = []
            for t in caps.tools:
                tool_dict = t.model_dump() if hasattr(t, "model_dump") else t
                name = (tool_dict.get("name", "") or "").lower()
                desc = (tool_dict.get("description", "") or "").lower()
                score = 0.0
                if q in name:
                    score = 0.95 if q == name else 0.80
                elif q in desc:
                    score = 0.60
                if score > 0:
                    matches.append({**tool_dict, "score": score})

            matches.sort(key=lambda x: x["score"], reverse=True)
            self.update_search_results(matches[:limit])
        except (AttributeError, KeyError, TypeError) as exc:
            logger.debug("Test search failed: %s", exc, exc_info=True)
