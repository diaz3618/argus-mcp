"""MCP Server Registry — client, models, cache, and catalog.

Provides a read-only client for the MCP Registry API v0.1,
a local JSON file cache for offline/fallback usage, and a
YAML/JSON catalog service for batch MCP server onboarding.
"""

from argus_mcp.registry.catalog import (
    CatalogEntry,
    CatalogEntryStatus,
    CatalogItemResult,
    CatalogParseError,
    CatalogResult,
    commit_catalog,
    parse_catalog,
    parse_catalog_file,
    stage_catalog,
)
from argus_mcp.registry.client import RegistryClient
from argus_mcp.registry.models import ServerEntry, ServerPage

__all__ = [
    "CatalogEntry",
    "CatalogEntryStatus",
    "CatalogItemResult",
    "CatalogParseError",
    "CatalogResult",
    "RegistryClient",
    "ServerEntry",
    "ServerPage",
    "commit_catalog",
    "parse_catalog",
    "parse_catalog_file",
    "stage_catalog",
]
