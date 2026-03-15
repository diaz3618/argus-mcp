"""Tests for argus_mcp.bridge.version_checker — version drift detection.

Covers:
- parse_semver (valid, invalid, v-prefix, edge cases)
- classify_drift (all severity levels)
- DriftResult (frozen, is_drifted property)
- VersionChecker with mock registry (check_all, check_one, get_drift_summary)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from argus_mcp.bridge.version_checker import (
    DriftResult,
    DriftSeverity,
    VersionChecker,
    classify_drift,
    parse_semver,
)

# parse_semver ────────────────────────────────────────────────────────


class TestParseSemver:
    def test_basic(self):
        assert parse_semver("1.2.3") == (1, 2, 3)

    def test_v_prefix(self):
        assert parse_semver("v1.0.0") == (1, 0, 0)

    def test_with_prerelease(self):
        # Only extracts major.minor.patch
        assert parse_semver("2.3.4-beta.1") == (2, 3, 4)

    def test_whitespace_stripped(self):
        assert parse_semver("  1.2.3  ") == (1, 2, 3)

    def test_zero_version(self):
        assert parse_semver("0.0.0") == (0, 0, 0)

    def test_large_numbers(self):
        assert parse_semver("100.200.300") == (100, 200, 300)

    def test_invalid_empty(self):
        assert parse_semver("") is None

    def test_invalid_no_dots(self):
        assert parse_semver("123") is None

    def test_invalid_partial(self):
        assert parse_semver("1.2") is None

    def test_invalid_letters(self):
        assert parse_semver("abc") is None

    def test_invalid_negative(self):
        assert parse_semver("-1.0.0") is None


# classify_drift ──────────────────────────────────────────────────────


class TestClassifyDrift:
    def test_current_same_version(self):
        assert classify_drift("1.2.3", "1.2.3") == DriftSeverity.CURRENT

    def test_current_ahead(self):
        assert classify_drift("2.0.0", "1.9.9") == DriftSeverity.CURRENT

    def test_patch_drift(self):
        assert classify_drift("1.2.3", "1.2.5") == DriftSeverity.PATCH

    def test_minor_drift(self):
        assert classify_drift("1.2.3", "1.3.0") == DriftSeverity.MINOR

    def test_major_drift(self):
        assert classify_drift("1.2.3", "2.0.0") == DriftSeverity.MAJOR

    def test_unknown_unparsable_current(self):
        assert classify_drift("latest", "1.0.0") == DriftSeverity.UNKNOWN

    def test_unknown_unparsable_latest(self):
        assert classify_drift("1.0.0", "nightly") == DriftSeverity.UNKNOWN

    def test_unknown_both_unparsable(self):
        assert classify_drift("foo", "bar") == DriftSeverity.UNKNOWN

    def test_v_prefix_handling(self):
        assert classify_drift("v1.0.0", "v1.0.1") == DriftSeverity.PATCH

    def test_major_drift_even_if_minor_also_differs(self):
        assert classify_drift("1.2.3", "3.0.0") == DriftSeverity.MAJOR


# DriftResult ─────────────────────────────────────────────────────────


class TestDriftResult:
    def test_is_drifted_for_patch(self):
        r = DriftResult("t1", "1.0.0", "1.0.1", DriftSeverity.PATCH)
        assert r.is_drifted is True

    def test_is_drifted_for_minor(self):
        r = DriftResult("t1", "1.0.0", "1.1.0", DriftSeverity.MINOR)
        assert r.is_drifted is True

    def test_is_drifted_for_major(self):
        r = DriftResult("t1", "1.0.0", "2.0.0", DriftSeverity.MAJOR)
        assert r.is_drifted is True

    def test_not_drifted_for_current(self):
        r = DriftResult("t1", "1.0.0", "1.0.0", DriftSeverity.CURRENT)
        assert r.is_drifted is False

    def test_not_drifted_for_unknown(self):
        r = DriftResult("t1", "???", "???", DriftSeverity.UNKNOWN)
        assert r.is_drifted is False

    def test_frozen(self):
        r = DriftResult("t1", "1.0.0", "2.0.0", DriftSeverity.MAJOR)
        with pytest.raises(AttributeError):
            r.name = "other"

    def test_backend_field(self):
        r = DriftResult("t1", "1.0.0", "2.0.0", DriftSeverity.MAJOR, backend="srv1")
        assert r.backend == "srv1"


# VersionChecker ──────────────────────────────────────────────────────


class TestVersionChecker:
    @pytest.mark.asyncio
    async def test_no_registry_returns_empty(self):
        checker = VersionChecker(registry_client=None)
        caps = {"tool1": {"version": "1.0.0"}}
        results = await checker.check_all(caps)
        assert results == []

    @pytest.mark.asyncio
    async def test_no_registry_check_one_returns_none(self):
        checker = VersionChecker(registry_client=None)
        result = await checker.check_one("tool1", "1.0.0")
        assert result is None

    @pytest.mark.asyncio
    async def test_check_all_with_mock_registry(self):
        registry = AsyncMock()
        registry.get_server = AsyncMock(return_value=SimpleNamespace(version="2.0.0"))

        checker = VersionChecker(registry_client=registry)
        caps = {
            "tool1": {"version": "1.0.0", "backend": "srv1"},
            "tool2": {"version": "2.0.0", "backend": "srv2"},
        }

        results = await checker.check_all(caps)
        assert len(results) == 2

        tool1_result = next(r for r in results if r.name == "tool1")
        assert tool1_result.severity == DriftSeverity.MAJOR
        assert tool1_result.backend == "srv1"

        tool2_result = next(r for r in results if r.name == "tool2")
        assert tool2_result.severity == DriftSeverity.CURRENT

    @pytest.mark.asyncio
    async def test_check_all_skips_no_version(self):
        registry = AsyncMock()
        checker = VersionChecker(registry_client=registry)
        caps = {"tool1": {}}  # no version key
        results = await checker.check_all(caps)
        assert results == []

    @pytest.mark.asyncio
    async def test_check_one_with_mock_registry(self):
        registry = AsyncMock()
        registry.get_server = AsyncMock(return_value=SimpleNamespace(version="1.1.0"))
        checker = VersionChecker(registry_client=registry)
        result = await checker.check_one("tool1", "1.0.0")
        assert result is not None
        assert result.severity == DriftSeverity.MINOR

    @pytest.mark.asyncio
    async def test_check_all_handles_registry_exception(self):
        registry = AsyncMock()
        registry.get_server = AsyncMock(side_effect=RuntimeError("network error"))
        checker = VersionChecker(registry_client=registry)
        caps = {"tool1": {"version": "1.0.0"}}
        # Should not raise — registry errors are caught
        results = await checker.check_all(caps)
        assert results == []

    def test_get_drift_summary(self):
        checker = VersionChecker()
        results = [
            DriftResult("a", "1.0.0", "1.0.0", DriftSeverity.CURRENT),
            DriftResult("b", "1.0.0", "1.0.1", DriftSeverity.PATCH),
            DriftResult("c", "1.0.0", "1.1.0", DriftSeverity.MINOR),
            DriftResult("d", "1.0.0", "2.0.0", DriftSeverity.MAJOR),
            DriftResult("e", "?", "?", DriftSeverity.UNKNOWN),
        ]
        summary = checker.get_drift_summary(results)
        assert summary["current"] == 1
        assert summary["patch"] == 1
        assert summary["minor"] == 1
        assert summary["major"] == 1
        assert summary["unknown"] == 1

    def test_get_drift_summary_empty(self):
        checker = VersionChecker()
        summary = checker.get_drift_summary([])
        assert all(v == 0 for v in summary.values())
        assert set(summary.keys()) == {s.value for s in DriftSeverity}
