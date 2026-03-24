"""In-memory tool search index using TF-IDF cosine similarity.

Falls back to a simple word-overlap scorer when scikit-learn is not
installed, so the heavy dependency remains optional.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from argus_mcp.constants import OPTIMIZER_SEARCH_LIMIT

logger = logging.getLogger(__name__)

# Try to use scikit-learn for proper TF-IDF; degrade gracefully.
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as _cosine

    _HAS_SKLEARN = True
except ImportError:  # pragma: no cover
    _HAS_SKLEARN = False

_SPLIT_RE = re.compile(r"[_\-\s]+")


def _tokenize(text: str) -> List[str]:
    """Lower-case, split on separators, strip empties."""
    return [t for t in _SPLIT_RE.split(text.lower()) if t]


def _simple_score(query_tokens: List[str], doc_tokens: List[str]) -> float:
    """Word-overlap + partial-match scorer (0-1 normalized)."""
    if not query_tokens or not doc_tokens:
        return 0.0
    doc_set = set(doc_tokens)
    doc_text = " ".join(doc_tokens)
    hits = 0.0
    for qt in query_tokens:
        if qt in doc_set:
            hits += 1.0
        elif any(qt in dt for dt in doc_tokens):
            hits += 0.5
        elif qt in doc_text:
            hits += 0.25
    return hits / len(query_tokens)


class ToolEntry:
    """Internal representation of a tool for indexing."""

    __slots__ = ("name", "description", "input_schema", "backend", "_search_text")

    def __init__(
        self,
        name: str,
        description: str = "",
        input_schema: Optional[Dict[str, Any]] = None,
        backend: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema or {}
        self.backend = backend
        self._search_text = f"{name} {description}".strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "backend": self.backend,
        }


class ToolIndex:
    """Searchable index of tool definitions.

    Uses scikit-learn TF-IDF + cosine similarity when available,
    otherwise falls back to simple word-overlap scoring.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolEntry] = {}
        self._tfidf_matrix: Any = None
        self._vectorizer: Any = None
        self._ordered_names: List[str] = []

    def _populate(
        self, tools: Sequence[Any], route_map: Optional[Dict[str, Tuple[str, str]]] = None
    ) -> None:
        """Parse *tools* into ``_tools`` dict (synchronous, no TF-IDF build)."""
        self._tools.clear()
        for t in tools:
            name = t.name if hasattr(t, "name") else t.get("name", "")
            desc = ""
            if hasattr(t, "description"):
                desc = t.description or ""
            elif isinstance(t, dict):
                desc = t.get("description", "")
            schema: Dict[str, Any] = {}
            if hasattr(t, "inputSchema"):
                schema = t.inputSchema or {}
            elif isinstance(t, dict):
                schema = t.get("inputSchema", t.get("input_schema", {})) or {}

            backend = ""
            if route_map and name in route_map:
                backend = route_map[name][0]

            self._tools[name] = ToolEntry(
                name=name,
                description=desc,
                input_schema=schema,
                backend=backend,
            )

    async def store(
        self, tools: Sequence[Any], route_map: Optional[Dict[str, Tuple[str, str]]] = None
    ) -> None:
        """Index a list of MCP Tool objects (or dicts) — **async**.

        The TF-IDF ``fit_transform()`` call is offloaded to a thread
        via ``asyncio.to_thread`` to avoid blocking the event loop
        to avoid blocking the event loop.

        Parameters
        ----------
        tools:
            List of ``mcp.types.Tool`` (or dicts with name/description/inputSchema).
        route_map:
            Optional mapping ``tool_name → (backend_name, original_name)``.
        """
        self._populate(tools, route_map)

        import asyncio

        await asyncio.to_thread(self._build_tfidf)
        logger.info("ToolIndex: indexed %d tools (sklearn=%s)", len(self._tools), _HAS_SKLEARN)

    def store_sync(
        self, tools: Sequence[Any], route_map: Optional[Dict[str, Tuple[str, str]]] = None
    ) -> None:
        """Synchronous variant of :meth:`store` for non-async contexts and tests."""
        self._populate(tools, route_map)
        self._build_tfidf()
        logger.info("ToolIndex: indexed %d tools (sklearn=%s)", len(self._tools), _HAS_SKLEARN)

    def _build_tfidf(self) -> None:
        """Build TF-IDF matrix from stored tools."""
        if not _HAS_SKLEARN or not self._tools:
            self._tfidf_matrix = None
            self._vectorizer = None
            self._ordered_names = list(self._tools.keys())
            return

        self._ordered_names = list(self._tools.keys())
        corpus = [self._tools[n]._search_text for n in self._ordered_names]
        self._vectorizer = TfidfVectorizer(
            token_pattern=r"[a-zA-Z0-9_]+",
            lowercase=True,
            stop_words=None,  # keep all tokens for tool names
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(corpus)

    def search(self, query: str, limit: int = OPTIMIZER_SEARCH_LIMIT) -> List[Dict[str, Any]]:
        """Search for tools matching *query*.

        Returns list of dicts: ``{name, description, input_schema, backend, score}``.
        """
        if not self._tools:
            return []

        if _HAS_SKLEARN and self._tfidf_matrix is not None and self._vectorizer is not None:
            return self._search_tfidf(query, limit)
        return self._search_simple(query, limit)

    def _search_tfidf(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """TF-IDF cosine similarity search."""
        query_vec = self._vectorizer.transform([query])
        scores = _cosine(query_vec, self._tfidf_matrix).flatten()

        results: List[Tuple[float, ToolEntry]] = []
        for idx, score in enumerate(scores):
            if score > 0.0:
                name = self._ordered_names[idx]
                results.append((float(score), self._tools[name]))

        results.sort(key=lambda x: x[0], reverse=True)
        return [{**entry.to_dict(), "score": round(score, 4)} for score, entry in results[:limit]]

    def _search_simple(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Fallback word-overlap search."""
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        results: List[Tuple[float, ToolEntry]] = []
        for entry in self._tools.values():
            doc_tokens = _tokenize(entry._search_text)
            score = _simple_score(query_tokens, doc_tokens)
            if score > 0.0:
                results.append((score, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return [{**entry.to_dict(), "score": round(score, 4)} for score, entry in results[:limit]]

    def get(self, name: str) -> Optional[ToolEntry]:
        """Get a tool by exact name."""
        return self._tools.get(name)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())
