"""Unit test fixtures — fast, no I/O, no network."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block accidental network calls in unit tests."""
    import socket

    def _deny(*args: object, **kwargs: object) -> None:  # noqa: ARG001
        msg = "Unit tests must not open network connections"
        raise RuntimeError(msg)

    monkeypatch.setattr(socket, "socket", _deny)
