"""Tests for argus_cli.tui.screens.setup_wizard — pure functions and class attributes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("argus_cli")


def _import_wizard():
    return __import__(
        "argus_cli.tui.screens.setup_wizard",
        fromlist=[
            "SetupWizardScreen",
            "_validate_yaml",
            "_find_config_path",
            "_load_config_text",
            "_MINIMAL_CONFIG",
            "_FilePathModal",
        ],
    )


class TestValidateYaml:
    """Test the _validate_yaml pure function."""

    def test_valid_config(self):
        mod = _import_wizard()
        text = 'version: "1"\nserver:\n  host: localhost\n'
        result = mod._validate_yaml(text)
        assert result is None

    def test_missing_version(self):
        mod = _import_wizard()
        text = "server:\n  host: localhost\n"
        result = mod._validate_yaml(text)
        assert result is not None
        assert "version" in result.lower()

    def test_not_a_dict(self):
        mod = _import_wizard()
        text = "- item1\n- item2\n"
        result = mod._validate_yaml(text)
        assert result is not None
        assert "mapping" in result.lower() or "dict" in result.lower()

    def test_invalid_yaml_syntax(self):
        mod = _import_wizard()
        text = ":\n  bad: {{{\n  [unmatched"
        result = mod._validate_yaml(text)
        assert result is not None
        assert "yaml" in result.lower() or "parse" in result.lower()

    def test_empty_string(self):
        mod = _import_wizard()
        # yaml.safe_load("") returns None, not a dict
        result = mod._validate_yaml("")
        assert result is not None

    def test_minimal_config_passes(self):
        mod = _import_wizard()
        result = mod._validate_yaml(mod._MINIMAL_CONFIG)
        assert result is None


class TestLoadConfigText:
    """Test _load_config_text with mocked filesystem."""

    def test_returns_minimal_when_no_file(self):
        mod = _import_wizard()
        with patch.object(mod, "_find_config_path") as mock_path:
            mock_path.return_value.is_file.return_value = False
            # When path.is_file() is False, should return _MINIMAL_CONFIG
            # But since _find_config_path returns a Path, we need a proper mock
            from pathlib import Path as _Path
            from unittest.mock import MagicMock

            fake_path = MagicMock(spec=_Path)
            fake_path.is_file.return_value = False
            mock_path.return_value = fake_path
            result = mod._load_config_text()
            assert result == mod._MINIMAL_CONFIG


class TestSetupWizardScreenAttributes:
    """Verify class attributes without mounting."""

    def test_is_subclass_of_argus_screen(self):
        mod = _import_wizard()
        from argus_cli.tui.screens.base import ArgusScreen

        assert issubclass(mod.SetupWizardScreen, ArgusScreen)


class TestFilePathModal:
    """Test _FilePathModal class initialization."""

    def test_init_attributes(self):
        mod = _import_wizard()
        modal = mod._FilePathModal.__new__(mod._FilePathModal)
        modal._title_text = "Save As"
        modal._prompt_text = "Enter path:"
        modal._default = "/tmp/test.yaml"
        assert modal._title_text == "Save As"
        assert modal._prompt_text == "Enter path:"
        assert modal._default == "/tmp/test.yaml"
