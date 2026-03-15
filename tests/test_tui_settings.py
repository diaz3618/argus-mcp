"""Tests for argus_mcp.tui.settings — persistent TUI settings.

Covers:
- ALL_THEMES and DEFAULT_ENABLED lists
- _default_settings() structure
- load_settings() from file, missing file, corrupt file
- save_settings() creates file and dir
"""

from __future__ import annotations

import json
from unittest.mock import patch

from argus_mcp.tui.settings import (
    ALL_THEMES,
    DEFAULT_ENABLED,
    _default_settings,
    load_settings,
    save_settings,
)


class TestThemeLists:
    def test_all_themes_count(self):
        assert len(ALL_THEMES) == 20

    def test_all_themes_are_strings(self):
        for t in ALL_THEMES:
            assert isinstance(t, str)

    def test_default_enabled_subset_of_all(self):
        """Every default-enabled theme must be in ALL_THEMES."""
        for t in DEFAULT_ENABLED:
            assert t in ALL_THEMES, f"{t} not in ALL_THEMES"

    def test_default_enabled_has_light_and_dark(self):
        assert "textual-dark" in DEFAULT_ENABLED
        assert "textual-light" in DEFAULT_ENABLED

    def test_no_duplicates_in_all(self):
        assert len(ALL_THEMES) == len(set(ALL_THEMES))

    def test_no_duplicates_in_default(self):
        assert len(DEFAULT_ENABLED) == len(set(DEFAULT_ENABLED))


class TestDefaultSettings:
    def test_structure(self):
        settings = _default_settings()
        assert "theme" in settings
        assert "enabled_themes" in settings

    def test_default_theme(self):
        assert _default_settings()["theme"] == "textual-dark"

    def test_enabled_themes_match_default(self):
        assert _default_settings()["enabled_themes"] == DEFAULT_ENABLED

    def test_returns_new_copy(self):
        """Each call returns a fresh dict (not shared reference)."""
        a = _default_settings()
        b = _default_settings()
        assert a is not b
        assert a["enabled_themes"] is not b["enabled_themes"]


class TestLoadSettings:
    def test_missing_file_returns_defaults(self, tmp_path):
        with patch("argus_mcp.tui.settings._SETTINGS_FILE", str(tmp_path / "nonexistent.json")):
            result = load_settings()
        assert result == _default_settings()

    def test_valid_file(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        data = {"theme": "nord", "enabled_themes": ["nord", "dracula"]}
        settings_file.write_text(json.dumps(data))

        with patch("argus_mcp.tui.settings._SETTINGS_FILE", str(settings_file)):
            result = load_settings()

        assert result["theme"] == "nord"
        assert result["enabled_themes"] == ["nord", "dracula"]

    def test_merges_missing_keys(self, tmp_path):
        """If file has partial data, defaults fill in missing keys."""
        settings_file = tmp_path / "settings.json"
        data = {"theme": "monokai"}  # missing enabled_themes
        settings_file.write_text(json.dumps(data))

        with patch("argus_mcp.tui.settings._SETTINGS_FILE", str(settings_file)):
            result = load_settings()

        assert result["theme"] == "monokai"
        assert "enabled_themes" in result
        assert result["enabled_themes"] == DEFAULT_ENABLED

    def test_corrupt_file_returns_defaults(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("NOT VALID JSON {{{")

        with patch("argus_mcp.tui.settings._SETTINGS_FILE", str(settings_file)):
            result = load_settings()

        assert result == _default_settings()


class TestSaveSettings:
    def test_creates_file(self, tmp_path):
        settings_file = tmp_path / "subdir" / "settings.json"
        with patch("argus_mcp.tui.settings._SETTINGS_FILE", str(settings_file)):
            with patch("argus_mcp.tui.settings._SETTINGS_DIR", str(tmp_path / "subdir")):
                save_settings({"theme": "dracula", "enabled_themes": ["dracula"]})

        assert settings_file.exists()
        data = json.loads(settings_file.read_text())
        assert data["theme"] == "dracula"

    def test_overwrites_existing(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"theme": "old"}))

        with patch("argus_mcp.tui.settings._SETTINGS_FILE", str(settings_file)):
            with patch("argus_mcp.tui.settings._SETTINGS_DIR", str(tmp_path)):
                save_settings({"theme": "new"})

        data = json.loads(settings_file.read_text())
        assert data["theme"] == "new"

    def test_handles_write_error_gracefully(self, tmp_path):
        """If writing fails, it logs but doesn't raise."""
        with patch("argus_mcp.tui.settings._SETTINGS_FILE", "/dev/null/impossible"):
            with patch("argus_mcp.tui.settings._SETTINGS_DIR", "/dev/null"):
                # Should not raise
                save_settings({"theme": "test"})
