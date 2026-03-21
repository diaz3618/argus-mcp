"""Tests for the optimizer module"""

from __future__ import annotations

import pytest

from argus_mcp.bridge.optimizer.meta_tools import (
    CALL_TOOL_DEF,
    CALL_TOOL_NAME,
    FIND_TOOL_DEF,
    FIND_TOOL_NAME,
    META_TOOLS,
    build_meta_tools,
)
from argus_mcp.bridge.optimizer.search import ToolIndex, _simple_score, _tokenize

# Helper: fake MCP Tool objects


class _FakeTool:
    """Minimal mock of mcp.types.Tool for testing."""

    def __init__(self, name: str, description: str = "", inputSchema: dict | None = None):
        self.name = name
        self.description = description or ""
        self.inputSchema = inputSchema or {}


def _make_tools() -> list[_FakeTool]:
    """Return a representative set of fake tools."""
    return [
        _FakeTool("read_file", "Read contents of a file from disk"),
        _FakeTool("write_file", "Write content to a file on disk"),
        _FakeTool("list_directory", "List files and directories in a given path"),
        _FakeTool("search_code", "Search for code patterns using regex"),
        _FakeTool("run_terminal", "Execute a shell command in a terminal"),
        _FakeTool("git_commit", "Create a git commit with a message"),
        _FakeTool("git_push", "Push commits to a remote repository"),
        _FakeTool("create_branch", "Create a new git branch"),
        _FakeTool("fetch_webpage", "Download content from a URL"),
        _FakeTool("send_email", "Send an email message"),
        _FakeTool("database_query", "Execute SQL query on a database"),
        _FakeTool("image_resize", "Resize an image to specified dimensions"),
    ]


def _make_route_map() -> dict[str, tuple[str, str]]:
    """Return a route map mapping tool names to (backend, original_name)."""
    return {
        "read_file": ("filesystem_server", "read_file"),
        "write_file": ("filesystem_server", "write_file"),
        "list_directory": ("filesystem_server", "list_directory"),
        "search_code": ("code_server", "search_code"),
        "run_terminal": ("shell_server", "run_terminal"),
        "git_commit": ("git_server", "git_commit"),
        "git_push": ("git_server", "git_push"),
        "create_branch": ("git_server", "create_branch"),
        "fetch_webpage": ("web_server", "fetch_webpage"),
        "send_email": ("email_server", "send_email"),
        "database_query": ("db_server", "database_query"),
        "image_resize": ("media_server", "image_resize"),
    }


#  ToolIndex tests


class TestToolIndexStore:
    """Tests for ToolIndex.store()."""

    def test_store_populates_index(self) -> None:
        idx = ToolIndex()
        idx.store_sync(_make_tools())
        assert idx.tool_count == 12

    def test_store_accepts_route_map(self) -> None:
        idx = ToolIndex()
        idx.store_sync(_make_tools(), _make_route_map())
        entry = idx.get("read_file")
        assert entry is not None
        assert entry.backend == "filesystem_server"

    def test_store_empty_list(self) -> None:
        idx = ToolIndex()
        idx.store_sync([])
        assert idx.tool_count == 0

    def test_store_replaces_previous(self) -> None:
        idx = ToolIndex()
        idx.store_sync(_make_tools())
        assert idx.tool_count == 12
        idx.store_sync([_FakeTool("only_tool")])
        assert idx.tool_count == 1

    def test_tool_names_property(self) -> None:
        idx = ToolIndex()
        idx.store_sync([_FakeTool("a"), _FakeTool("b"), _FakeTool("c")])
        assert set(idx.tool_names) == {"a", "b", "c"}


class TestToolIndexGet:
    """Tests for exact lookup."""

    def test_get_existing(self) -> None:
        idx = ToolIndex()
        idx.store_sync(_make_tools())
        entry = idx.get("git_commit")
        assert entry is not None
        assert entry.name == "git_commit"
        assert "git" in entry.description.lower()

    def test_get_missing(self) -> None:
        idx = ToolIndex()
        idx.store_sync(_make_tools())
        assert idx.get("nonexistent_tool") is None


class TestToolIndexSearch:
    """Tests for search quality."""

    @pytest.fixture()
    def index(self) -> ToolIndex:
        idx = ToolIndex()
        idx.store_sync(_make_tools(), _make_route_map())
        return idx

    def test_search_returns_results(self, index: ToolIndex) -> None:
        results = index.search("read file")
        assert len(results) > 0

    def test_search_result_structure(self, index: ToolIndex) -> None:
        results = index.search("file", limit=1)
        assert len(results) >= 1
        r = results[0]
        assert "name" in r
        assert "description" in r
        assert "input_schema" in r
        assert "backend" in r
        assert "score" in r
        assert isinstance(r["score"], float)
        assert r["score"] > 0.0

    def test_search_file_operations(self, index: ToolIndex) -> None:
        """'file' should match read_file, write_file, list_directory."""
        results = index.search("file", limit=5)
        names = {r["name"] for r in results}
        assert "read_file" in names
        assert "write_file" in names

    def test_search_git_operations(self, index: ToolIndex) -> None:
        """'git' should match git_commit at minimum."""
        results = index.search("git", limit=5)
        names = {r["name"] for r in results}
        assert "git_commit" in names
        # git_push may or may not rank in top-5 since its description
        # says "Push commits to a remote repository" (no "git" token).

    def test_search_respects_limit(self, index: ToolIndex) -> None:
        results = index.search("tool", limit=3)
        assert len(results) <= 3

    def test_search_empty_query(self, index: ToolIndex) -> None:
        results = index.search("")
        # Empty query should return empty or all with 0 score
        assert isinstance(results, list)

    def test_search_no_match(self, index: ToolIndex) -> None:
        results = index.search("xyzzynonexistent")
        assert len(results) == 0

    def test_search_correct_tool_in_top3(self, index: ToolIndex) -> None:
        """Acceptance: correct tool in top-3 for 90%+ of queries."""
        queries_and_expected = [
            ("read a file", "read_file"),
            ("write a file", "write_file"),
            ("list directory", "list_directory"),
            ("search code", "search_code"),
            ("run command", "run_terminal"),
            ("git commit", "git_commit"),
            ("push commits", "git_push"),
            ("create branch", "create_branch"),
            ("download url", "fetch_webpage"),
            ("send email", "send_email"),
            ("sql query database", "database_query"),
            ("resize image", "image_resize"),
        ]
        hits = 0
        for query, expected in queries_and_expected:
            results = index.search(query, limit=3)
            top_names = {r["name"] for r in results}
            if expected in top_names:
                hits += 1

        accuracy = hits / len(queries_and_expected)
        assert accuracy >= 0.9, (
            f"Search accuracy {accuracy:.0%} < 90%: "
            f"{hits}/{len(queries_and_expected)} queries matched"
        )

    def test_search_includes_backend(self, index: ToolIndex) -> None:
        results = index.search("file", limit=1)
        assert len(results) >= 1
        assert results[0]["backend"] != ""

    def test_search_scores_sorted_descending(self, index: ToolIndex) -> None:
        results = index.search("file", limit=10)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_index_search(self) -> None:
        idx = ToolIndex()
        idx.store_sync([])
        assert idx.search("anything") == []


#  Simple scorer tests


class TestSimpleScorer:
    """Tests for the fallback word-overlap scorer."""

    def test_tokenize_basic(self) -> None:
        assert _tokenize("hello_world") == ["hello", "world"]

    def test_tokenize_mixed_separators(self) -> None:
        tokens = _tokenize("read-file_path name")
        assert tokens == ["read", "file", "path", "name"]

    def test_simple_score_exact_match(self) -> None:
        score = _simple_score(["read", "file"], ["read", "file", "disk"])
        assert score > 0.5

    def test_simple_score_no_match(self) -> None:
        score = _simple_score(["xyz"], ["read", "file"])
        assert score == 0.0

    def test_simple_score_empty(self) -> None:
        assert _simple_score([], ["a"]) == 0.0
        assert _simple_score(["a"], []) == 0.0


#  Meta-tools tests


class TestMetaTools:
    """Tests for the meta-tool definitions."""

    def test_find_tool_definition(self) -> None:
        assert FIND_TOOL_DEF.name == "find_tool"
        assert "search" in FIND_TOOL_DEF.description.lower()
        assert FIND_TOOL_DEF.inputSchema["properties"]["query"]["type"] == "string"

    def test_call_tool_definition(self) -> None:
        assert CALL_TOOL_DEF.name == "call_tool"
        assert "call" in CALL_TOOL_DEF.description.lower()
        assert CALL_TOOL_DEF.inputSchema["properties"]["name"]["type"] == "string"

    def test_meta_tools_list(self) -> None:
        assert len(META_TOOLS) == 2
        names = {t.name for t in META_TOOLS}
        assert names == {FIND_TOOL_NAME, CALL_TOOL_NAME}

    def test_build_meta_tools(self) -> None:
        tools = build_meta_tools()
        assert len(tools) == 2

    def test_build_meta_tools_with_keep_list(self) -> None:
        tools = build_meta_tools(keep_list=["my_tool"])
        # keep_list doesn't add actual Tool objects — that's the handler's job
        assert len(tools) == 2


#  OptimizerConfig tests


class TestOptimizerConfig:
    """Tests for the optimizer configuration model."""

    def test_default_disabled(self) -> None:
        from argus_mcp.config.schema import OptimizerConfig

        cfg = OptimizerConfig()
        assert cfg.enabled is False
        assert cfg.keep_tools == []

    def test_enabled_with_keep_list(self) -> None:
        from argus_mcp.config.schema import OptimizerConfig

        cfg = OptimizerConfig(enabled=True, keep_tools=["tool_a", "tool_b"])
        assert cfg.enabled is True
        assert cfg.keep_tools == ["tool_a", "tool_b"]

    def test_argus_config_has_optimizer(self) -> None:
        from argus_mcp.config.schema import ArgusConfig

        cfg = ArgusConfig(version="1", backends={})
        assert cfg.optimizer.enabled is False


#  Integration-level: dict-based tool input


class TestToolIndexDictInput:
    """ToolIndex should also accept dict-based tools (not just mcp.types.Tool)."""

    def test_store_dicts(self) -> None:
        idx = ToolIndex()
        idx.store_sync(
            [
                {"name": "tool_a", "description": "Alpha tool"},
                {"name": "tool_b", "description": "Beta tool"},
            ]
        )
        assert idx.tool_count == 2
        assert idx.get("tool_a") is not None

    def test_search_dicts(self) -> None:
        idx = ToolIndex()
        idx.store_sync(
            [
                {"name": "read_file", "description": "Read file contents"},
                {"name": "write_file", "description": "Write file contents"},
            ]
        )
        results = idx.search("read", limit=1)
        assert len(results) >= 1
        assert results[0]["name"] == "read_file"
