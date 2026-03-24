"""Argus CLI — Interactive command-line interface for Argus MCP."""

__all__ = ["__version__"]

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("argus-cli")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
