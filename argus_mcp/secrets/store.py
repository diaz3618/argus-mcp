"""Secret store — high-level API for secret management.

Combines a :class:`SecretProvider` backend with convenience helpers.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from .providers import SecretProvider, create_provider

logger = logging.getLogger(__name__)


class SecretStore:
    """Unified secret management facade.

    Parameters
    ----------
    provider_type:
        One of ``env``, ``file``, ``keyring``.
    kwargs:
        Extra keyword arguments forwarded to the provider constructor
        (e.g. ``path`` for ``FileProvider``).
    """

    def __init__(self, provider_type: str = "env", **kwargs: str) -> None:
        self._provider: SecretProvider = create_provider(provider_type, **kwargs)
        self._provider_type = provider_type

    @property
    def provider_type(self) -> str:
        return self._provider_type

    def get(self, name: str) -> Optional[str]:
        """Retrieve a secret value by name."""
        return self._provider.get(name)

    def set(self, name: str, value: str) -> None:
        """Store or update a secret."""
        self._provider.set(name, value)
        # nosemgrep: python-logger-credential-disclosure (logs name, not value)
        logger.debug("Secret '%s' stored via %s provider", name, self._provider_type)

    def delete(self, name: str) -> None:
        """Delete a secret."""
        self._provider.delete(name)
        # nosemgrep: python-logger-credential-disclosure (logs name, not value)
        logger.debug("Secret '%s' deleted via %s provider", name, self._provider_type)

    def list_names(self) -> List[str]:
        """List all secret names."""
        return self._provider.list_names()

    def exists(self, name: str) -> bool:
        """Check whether a secret exists."""
        return self._provider.get(name) is not None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SecretStore":
        """Create a SecretStore from a config dictionary.

        Expected keys::

            {
                "provider": "env" | "file" | "keyring",
                "path": "secrets.enc"          // only for file provider
            }
        """
        provider_type = config.get("provider", "env")
        kwargs = {}
        if provider_type == "file" and "path" in config:
            kwargs["path"] = config["path"]
        return cls(provider_type=provider_type, **kwargs)
