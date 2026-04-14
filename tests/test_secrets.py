"""Tests for argus_mcp.secrets — providers, store, resolver.

Covers:
- EnvProvider (env key mapping, CRUD, list_names)
- SecretStore facade (get/set/delete/exists/list_names, from_config)
- create_provider factory (valid types, unknown → ValueError)
- resolve_secrets (walk, strict mode → raises, non-strict → warns)
- find_secret_references
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from argus_mcp.secrets.providers import EnvProvider, create_provider
from argus_mcp.secrets.resolver import (
    SecretResolutionError,
    find_secret_references,
    resolve_secrets,
)
from argus_mcp.secrets.store import SecretStore

# EnvProvider


class TestEnvProvider:
    def test_env_key_mapping(self):
        p = EnvProvider()
        assert p._env_key("my-api-key") == "SECRET_MY_API_KEY"
        assert p._env_key("simple") == "SECRET_SIMPLE"

    def test_get_set_delete(self, monkeypatch):
        p = EnvProvider()
        monkeypatch.delenv("SECRET_TEST_KEY", raising=False)

        assert p.get("test-key") is None

        p.set("test-key", "val123")
        assert p.get("test-key") == "val123"

        p.delete("test-key")
        assert p.get("test-key") is None

    def test_delete_nonexistent(self, monkeypatch):
        p = EnvProvider()
        monkeypatch.delenv("SECRET_NOPE", raising=False)
        p.delete("nope")  # should not raise

    def test_list_names(self, monkeypatch):
        # Clear any existing SECRET_ vars first
        for key in list(os.environ):
            if key.startswith("SECRET_"):
                monkeypatch.delenv(key, raising=False)

        p = EnvProvider()
        monkeypatch.setenv("SECRET_MY_KEY", "v1")
        monkeypatch.setenv("SECRET_OTHER", "v2")
        names = p.list_names()
        assert "my-key" in names
        assert "other" in names

    def test_list_names_empty(self, monkeypatch):
        for key in list(os.environ):
            if key.startswith("SECRET_"):
                monkeypatch.delenv(key, raising=False)
        p = EnvProvider()
        assert p.list_names() == []


# create_provider


class TestCreateProvider:
    def test_env(self):
        p = create_provider("env")
        assert isinstance(p, EnvProvider)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            create_provider("redis")

    def test_file_type(self):
        """FileProvider is created (requires cryptography for actual use)."""
        from argus_mcp.secrets.providers import FileProvider

        p = create_provider("file", path="/tmp/test.enc")
        assert isinstance(p, FileProvider)

    def test_keyring_type(self):
        from argus_mcp.secrets.providers import KeyringProvider

        p = create_provider("keyring")
        assert isinstance(p, KeyringProvider)


# SecretStore


class TestSecretStore:
    def test_provider_type(self):
        store = SecretStore(provider_type="env")
        assert store.provider_type == "env"

    def test_get_set_delete(self, monkeypatch):
        monkeypatch.delenv("SECRET_MYVAL", raising=False)
        store = SecretStore(provider_type="env")

        assert store.get("myval") is None
        assert store.exists("myval") is False

        store.set("myval", "hello")
        assert store.get("myval") == "hello"
        assert store.exists("myval") is True

        store.delete("myval")
        assert store.exists("myval") is False

    def test_list_names(self, monkeypatch):
        for key in list(os.environ):
            if key.startswith("SECRET_"):
                monkeypatch.delenv(key, raising=False)
        store = SecretStore(provider_type="env")
        store.set("a", "1")
        store.set("b", "2")
        names = store.list_names()
        assert "a" in names
        assert "b" in names

    def test_from_config_env(self):
        store = SecretStore.from_config({"provider": "env"})
        assert store.provider_type == "env"

    def test_from_config_file(self):
        store = SecretStore.from_config({"provider": "file", "path": "/tmp/s.enc"})
        assert store.provider_type == "file"

    def test_from_config_default(self):
        store = SecretStore.from_config({})
        assert store.provider_type == "env"


# resolve_secrets


class TestResolveSecrets:
    def _make_store(self, secrets: dict):
        """Create a SecretStore with mock provider."""
        store = SecretStore(provider_type="env")
        mock_provider = MagicMock()
        mock_provider.get = MagicMock(side_effect=lambda n: secrets.get(n))
        store._provider = mock_provider
        return store

    def test_resolve_string(self):
        store = self._make_store({"api-key": "actual-value"})
        config = {"token": "secret:api-key"}
        result = resolve_secrets(config, store)
        assert result["token"] == "actual-value"

    def test_non_secret_unchanged(self):
        store = self._make_store({})
        config = {"plain": "hello", "number": 42}
        result = resolve_secrets(config, store)
        assert result == config

    def test_nested_dict(self):
        store = self._make_store({"db-pass": "p@ss"})
        config = {"backend": {"auth": {"password": "secret:db-pass"}}}
        result = resolve_secrets(config, store)
        assert result["backend"]["auth"]["password"] == "p@ss"

    def test_list_values(self):
        store = self._make_store({"k1": "v1", "k2": "v2"})
        config = {"keys": ["secret:k1", "secret:k2", "plain"]}
        result = resolve_secrets(config, store)
        assert result["keys"] == ["v1", "v2", "plain"]

    def test_missing_secret_non_strict(self):
        store = self._make_store({})
        config = {"token": "secret:missing"}
        result = resolve_secrets(config, store)
        # Non-strict: left as-is
        assert result["token"] == "secret:missing"

    def test_missing_secret_strict(self):
        store = self._make_store({})
        config = {"token": "secret:missing"}
        with pytest.raises(SecretResolutionError, match="missing"):
            resolve_secrets(config, store, strict=True)

    def test_original_not_mutated(self):
        store = self._make_store({"k": "v"})
        config = {"token": "secret:k"}
        result = resolve_secrets(config, store)
        assert config["token"] == "secret:k"
        assert result["token"] == "v"


# find_secret_references


class TestFindSecretReferences:
    def test_flat(self):
        config = {"a": "secret:key1", "b": "plain"}
        assert find_secret_references(config) == ["key1"]

    def test_nested(self):
        config = {"a": {"b": "secret:k1"}, "c": ["secret:k2"]}
        refs = find_secret_references(config)
        assert sorted(refs) == ["k1", "k2"]

    def test_none(self):
        assert find_secret_references({"a": "plain", "b": 42}) == []

    def test_empty(self):
        assert find_secret_references({}) == []

    def test_multiple_same(self):
        config = {"a": "secret:x", "b": "secret:x"}
        refs = find_secret_references(config)
        assert refs.count("x") == 2


# _walk depth limit


class TestWalkDepthLimit:
    def _make_store(self, data):
        store = MagicMock(spec=SecretStore)
        store.get.side_effect = lambda name: data.get(name)
        return store

    def test_walk_depth_limit_exceeded(self):
        nested: dict = {"leaf": "val"}
        for _ in range(25):
            nested = {"child": nested}
        store = self._make_store({})
        with pytest.raises(ValueError, match="recursion depth limit"):
            resolve_secrets(nested, store)

    def test_walk_normal_depth_succeeds(self):
        nested: dict = {"leaf": "val"}
        for _ in range(15):
            nested = {"child": nested}
        store = self._make_store({})
        result = resolve_secrets(nested, store)
        assert result is not None


# FileProvider permission check


class TestFileProviderPermissions:
    def test_file_provider_warns_group_readable(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        fernet = Fernet(key)
        monkeypatch.setenv("ARGUS_SECRET_KEY", key.decode())

        secret_file = tmp_path / "secrets.enc"
        secret_file.write_bytes(fernet.encrypt(b'{"k": "v"}'))
        os.chmod(secret_file, 0o640)

        from argus_mcp.secrets.providers import FileProvider

        fp = FileProvider(path=str(secret_file))
        with patch("argus_mcp.secrets.providers.logger") as mock_logger:
            fp.get("k")
        mock_logger.warning.assert_called()
        warn_msg = mock_logger.warning.call_args[0][0]
        assert "group-readable" in warn_msg

    def test_file_provider_warns_world_readable(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        fernet = Fernet(key)
        monkeypatch.setenv("ARGUS_SECRET_KEY", key.decode())

        secret_file = tmp_path / "secrets.enc"
        secret_file.write_bytes(fernet.encrypt(b'{"k": "v"}'))
        os.chmod(secret_file, 0o644)

        from argus_mcp.secrets.providers import FileProvider

        fp = FileProvider(path=str(secret_file))
        with patch("argus_mcp.secrets.providers.logger") as mock_logger:
            fp.get("k")
        mock_logger.warning.assert_called()
        warn_msg = mock_logger.warning.call_args[0][0]
        assert "world-readable" in warn_msg

    def test_file_provider_no_warn_600(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        fernet = Fernet(key)
        monkeypatch.setenv("ARGUS_SECRET_KEY", key.decode())

        secret_file = tmp_path / "secrets.enc"
        secret_file.write_bytes(fernet.encrypt(b'{"k": "v"}'))
        os.chmod(secret_file, 0o600)

        from argus_mcp.secrets.providers import FileProvider

        fp = FileProvider(path=str(secret_file))
        with patch("argus_mcp.secrets.providers.logger") as mock_logger:
            fp.get("k")
        # Should NOT have warned about permissions
        for call in mock_logger.warning.call_args_list:
            msg = call[0][0] if call[0] else ""
            assert "group-readable" not in msg
            assert "world-readable" not in msg
