"""Secret storage providers — backends for secret retrieval.

Providers implement a simple interface::

    class SecretProvider:
        def get(self, name: str) -> Optional[str]: ...
        def set(self, name: str, value: str) -> None: ...
        def delete(self, name: str) -> None: ...
        def list_names(self) -> List[str]: ...

Built-in providers:

* ``EnvProvider`` — reads from environment variables (``SECRET_<NAME>``)
* ``FileProvider`` — Fernet-encrypted JSON file
* ``KeyringProvider`` — OS keyring (via ``keyring`` package)
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SecretProvider(ABC):
    """Abstract base class for secret storage backends."""

    @abstractmethod
    def get(self, name: str) -> Optional[str]:
        """Retrieve a secret by name, or ``None`` if not found."""

    @abstractmethod
    def set(self, name: str, value: str) -> None:
        """Store a secret."""

    @abstractmethod
    def delete(self, name: str) -> None:
        """Remove a secret."""

    @abstractmethod
    def list_names(self) -> List[str]:
        """Return all stored secret names."""


class EnvProvider(SecretProvider):
    """Reads secrets from environment variables.

    The secret ``my-api-key`` maps to ``SECRET_MY_API_KEY`` (uppercased,
    hyphens to underscores, prefixed with ``SECRET_``).
    """

    def _env_key(self, name: str) -> str:
        return f"SECRET_{name.upper().replace('-', '_')}"

    def get(self, name: str) -> Optional[str]:
        return os.environ.get(self._env_key(name))

    def set(self, name: str, value: str) -> None:
        os.environ[self._env_key(name)] = value

    def delete(self, name: str) -> None:
        os.environ.pop(self._env_key(name), None)

    def list_names(self) -> List[str]:
        prefix = "SECRET_"
        return [
            k[len(prefix) :].lower().replace("_", "-") for k in os.environ if k.startswith(prefix)
        ]


class FileProvider(SecretProvider):
    """Stores secrets in a Fernet-encrypted JSON file.

    The master key is read from the ``ARGUS_SECRET_KEY`` environment
    variable.  If ``cryptography`` is not installed, raises on first use.

    Parameters
    ----------
    path:
        Path to the encrypted secrets file.
    """

    def __init__(self, path: str = "secrets.enc") -> None:
        self._path = path
        self._fernet: Optional[object] = None  # lazy

    def _ensure_fernet(self) -> object:
        if self._fernet is not None:
            return self._fernet

        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise RuntimeError(
                "cryptography package required for encrypted secrets. "
                "Install with: pip install cryptography"
            ) from exc

        key = os.environ.get("ARGUS_SECRET_KEY")
        if not key:
            raise RuntimeError(
                "ARGUS_SECRET_KEY environment variable must be set for encrypted secret storage."
            )

        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return self._fernet

    def _load(self) -> Dict[str, str]:
        if not os.path.exists(self._path):
            return {}
        fernet = self._ensure_fernet()
        try:
            with open(self._path, "rb") as f:
                encrypted = f.read()
            decrypted = fernet.decrypt(encrypted)  # type: ignore[attr-defined]
            loaded: Dict[str, str] = json.loads(decrypted)
            return loaded
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Failed to load/decrypt secrets file {self._path}: {exc}. "
                "Check that ARGUS_SECRET_KEY is correct and the file is not corrupted."
            ) from exc

    def _save(self, data: Dict[str, str]) -> None:
        fernet = self._ensure_fernet()
        plaintext = json.dumps(data).encode()
        encrypted = fernet.encrypt(plaintext)  # type: ignore[attr-defined]
        # Atomic write: write to temp file then rename
        import tempfile

        dir_name = os.path.dirname(os.path.abspath(self._path)) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".secrets_", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(encrypted)
            os.replace(tmp_path, self._path)
            # Restrict permissions to owner only
            os.chmod(self._path, 0o600)
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get(self, name: str) -> Optional[str]:
        return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        data = self._load()
        data[name] = value
        self._save(data)

    def delete(self, name: str) -> None:
        data = self._load()
        data.pop(name, None)
        self._save(data)

    def list_names(self) -> List[str]:
        return list(self._load().keys())


class KeyringProvider(SecretProvider):
    """Uses the OS keyring (macOS Keychain, GNOME Keyring, etc.).

    Requires the ``keyring`` package.
    """

    SERVICE_NAME = "argus-mcp"

    def __init__(self) -> None:
        self._keyring: Optional[object] = None
        self._names_key = "__argus_mcp_secret_names__"

    def _ensure_keyring(self) -> object:
        if self._keyring is not None:
            return self._keyring
        try:
            import keyring

            self._keyring = keyring
            return keyring
        except ImportError as exc:
            raise RuntimeError(
                "keyring package required. Install with: pip install keyring"
            ) from exc

    def get(self, name: str) -> Optional[str]:
        kr = self._ensure_keyring()
        result: Optional[str] = kr.get_password(self.SERVICE_NAME, name)  # type: ignore[attr-defined]
        return result

    def set(self, name: str, value: str) -> None:
        kr = self._ensure_keyring()
        kr.set_password(self.SERVICE_NAME, name, value)  # type: ignore[attr-defined]
        # Track names in a separate entry
        names = set(self.list_names())
        names.add(name)
        kr.set_password(self.SERVICE_NAME, self._names_key, json.dumps(sorted(names)))  # type: ignore[attr-defined]

    def delete(self, name: str) -> None:
        kr = self._ensure_keyring()
        try:
            kr.delete_password(self.SERVICE_NAME, name)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to delete secret '%s' from keyring: %s", name, exc, exc_info=True
            )
        names = set(self.list_names())
        names.discard(name)
        kr.set_password(self.SERVICE_NAME, self._names_key, json.dumps(sorted(names)))  # type: ignore[attr-defined]

    def list_names(self) -> List[str]:
        kr = self._ensure_keyring()
        raw = kr.get_password(self.SERVICE_NAME, self._names_key)  # type: ignore[attr-defined]
        if raw:
            try:
                loaded: List[str] = json.loads(raw)
                return loaded
            except json.JSONDecodeError:
                pass
        return []


def create_provider(provider_type: str = "env", **kwargs: str) -> SecretProvider:
    """Factory for secret providers."""
    if provider_type == "env":
        return EnvProvider()
    if provider_type == "file":
        return FileProvider(path=kwargs.get("path", "secrets.enc"))
    if provider_type == "keyring":
        return KeyringProvider()
    raise ValueError(f"Unknown secret provider type: {provider_type!r}")
