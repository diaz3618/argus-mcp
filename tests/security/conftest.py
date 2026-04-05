"""Security test fixtures — auth, token, injection tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.security


@pytest.fixture()
def inner_app() -> AsyncMock:
    """Mock ASGI inner application."""
    return AsyncMock()


@pytest.fixture()
def send_callable() -> AsyncMock:
    """Mock ASGI send callable for capturing responses."""
    return AsyncMock()
