"""HTTP client for the Argus MCP management API.

Provides an async wrapper around the ``/manage/v1/`` endpoints so that the
TUI can connect to a *running* Argus server over the network instead of
hosting one in-process.

.. note::
   The canonical client and schemas now live in :mod:`argus_mcp.api`.
   This module re-exports :class:`~argus_mcp.api.client.ApiClient` and
   :class:`~argus_mcp.api.client.ApiClientError` for backward compatibility.
"""

from __future__ import annotations

from argus_mcp.api.client import ApiClient, ApiClientError  # noqa: F401 — re-exports

__all__ = ["ApiClient", "ApiClientError"]
