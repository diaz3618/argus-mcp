"""Shared fixtures and markers for concurrency stress tests."""

from __future__ import annotations

import pytest

# Apply concurrency marker and a per-test timeout to every test in this package.
pytestmark = [pytest.mark.concurrency, pytest.mark.timeout(10)]
