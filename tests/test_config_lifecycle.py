"""Tests for Configuration Lifecycle.

Covers:
- Config export (export.py)
- Config import (import_handler.py)
- Metadata provenance (schema_backends.py MetadataProvenance)
- YAML Catalog Service (registry/catalog.py)
- Export/import round-trip
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from pydantic import ValidationError

from argus_mcp.config.export import (
    ExportFilter,
    ExportResult,
    SecretHandling,
    export_config,
)
from argus_mcp.config.import_handler import (
    ConflictStrategy,
    ImportResult,
    ImportValidationError,
    import_config,
    parse_import_payload,
)
from argus_mcp.config.schema import ArgusConfig
from argus_mcp.config.schema_backends import (
    MetadataProvenance,
    SseBackendConfig,
    StdioBackendConfig,
    StreamableHttpBackendConfig,
)
from argus_mcp.config.schema_registry import RegistryEntryConfig
from argus_mcp.registry.catalog import (
    CatalogEntry,
    CatalogEntryStatus,
    CatalogParseError,
    commit_catalog,
    parse_catalog,
    stage_catalog,
)

# Helpers


def _make_config(**overrides: Any) -> ArgusConfig:
    """Create a minimal ArgusConfig for testing."""
    defaults: Dict[str, Any] = {
        "backends": {
            "echo": {"type": "stdio", "command": "echo", "args": ["hello"]},
            "web": {"url": "https://example.com/mcp", "type": "sse"},
        },
        "registries": [
            {"name": "default", "url": "https://registry.example.com"},
        ],
    }
    defaults.update(overrides)
    return ArgusConfig(**defaults)


def _make_config_with_secrets() -> ArgusConfig:
    """Config with secret:* references for secret handling tests."""
    return ArgusConfig(
        backends={
            "private": {
                "url": "https://private.example.com/mcp",
                "type": "sse",
                "headers": {"Authorization": "secret:my_token"},
            },
            "stdio-srv": {"type": "stdio", "command": "srv", "env": {"API_KEY": "secret:api_key"}},
        },
    )


# Export tests


class TestExportConfig:
    """Tests for config export functionality."""

    def test_export_all_defaults(self) -> None:
        config = _make_config()
        result = export_config(config)
        assert isinstance(result, ExportResult)
        assert result.version == "1"
        assert result.export_id
        assert result.exported_at
        assert "backends" in result.data
        assert "registries" in result.data

    def test_export_id_format(self) -> None:
        config = _make_config()
        result = export_config(config)
        assert len(result.export_id) == 12

    def test_export_filter_by_backend_names(self) -> None:
        config = _make_config()
        ef = ExportFilter(backend_names={"echo"})
        result = export_config(config, export_filter=ef)
        backends = result.data.get("backends", {})
        assert "echo" in backends
        assert "web" not in backends

    def test_export_filter_entity_types(self) -> None:
        config = _make_config()
        ef = ExportFilter(entity_types={"backends"})
        result = export_config(config, export_filter=ef)
        assert "backends" in result.data
        assert "registries" not in result.data

    def test_export_secret_strip(self) -> None:
        config = _make_config_with_secrets()
        result = export_config(config, secret_handling=SecretHandling.STRIP)
        data = result.data
        private = data.get("backends", {}).get("private", {})
        headers = private.get("headers", {})
        assert "Authorization" not in headers or headers.get("Authorization") == ""

    def test_export_secret_mask(self) -> None:
        config = _make_config_with_secrets()
        result = export_config(config, secret_handling=SecretHandling.MASK)
        data = result.data
        private = data.get("backends", {}).get("private", {})
        headers = private.get("headers", {})
        auth_val = headers.get("Authorization", "")
        assert "***" in auth_val or auth_val == ""

    def test_export_secret_preserve(self) -> None:
        config = _make_config_with_secrets()
        result = export_config(config, secret_handling=SecretHandling.PRESERVE)
        data = result.data
        stdio_srv = data.get("backends", {}).get("stdio-srv", {})
        env = stdio_srv.get("env", {})
        assert env.get("API_KEY") == "secret:api_key"

    def test_export_entity_counts(self) -> None:
        config = _make_config()
        result = export_config(config)
        assert result.entity_counts.get("backends", 0) == 2
        assert result.entity_counts.get("registries", 0) == 1

    def test_export_empty_config(self) -> None:
        config = ArgusConfig()
        result = export_config(config)
        assert result.entity_counts.get("backends", 0) == 0

    def test_export_feature_flags(self) -> None:
        config = _make_config(feature_flags={"dark_mode": True, "beta": False})
        ef = ExportFilter(entity_types={"feature_flags"})
        result = export_config(config, export_filter=ef)
        flags = result.data.get("feature_flags", {})
        assert flags.get("dark_mode") is True


# Import tests


class TestParseImportPayload:
    """Tests for YAML import parsing."""

    def test_parse_valid_yaml(self) -> None:
        yaml_str = """
backends:
  test-srv:
    command: echo
    args: [hello]
"""
        payload = parse_import_payload(yaml_str)
        assert "backends" in payload

    def test_parse_rejects_oversized(self) -> None:
        huge = "x" * (6 * 1024 * 1024)
        with pytest.raises(ImportValidationError, match="exceeds"):
            parse_import_payload(huge)

    def test_parse_rejects_invalid_yaml(self) -> None:
        with pytest.raises(ImportValidationError, match="Invalid YAML"):
            parse_import_payload("{: bad: yaml: [}")

    def test_parse_rejects_non_dict(self) -> None:
        with pytest.raises(ImportValidationError, match="mapping"):
            parse_import_payload("- item1\n- item2")


class TestImportConfig:
    """Tests for config import with conflict strategies."""

    def test_import_add_new_backend(self) -> None:
        config = _make_config()
        payload = {"backends": {"new-srv": {"type": "stdio", "command": "new", "args": []}}}
        result = import_config(config, payload)
        assert isinstance(result, ImportResult)
        assert result.added_count == 1
        assert "new-srv" in config.backends

    def test_import_skip_existing(self) -> None:
        config = _make_config()
        payload = {"backends": {"echo": {"type": "stdio", "command": "different"}}}
        result = import_config(config, payload, conflict_strategy=ConflictStrategy.SKIP)
        assert result.skipped_count == 1

    def test_import_update_existing(self) -> None:
        config = _make_config()
        payload = {"backends": {"echo": {"type": "stdio", "command": "updated", "args": ["world"]}}}
        result = import_config(config, payload, conflict_strategy=ConflictStrategy.UPDATE)
        assert result.updated_count == 1

    def test_import_rename_conflict(self) -> None:
        config = _make_config()
        payload = {"backends": {"echo": {"type": "stdio", "command": "echo2"}}}
        result = import_config(config, payload, conflict_strategy=ConflictStrategy.RENAME)
        renamed = [i for i in result.items if i.new_name]
        assert len(renamed) == 1
        assert renamed[0].new_name in config.backends

    def test_import_fail_conflict(self) -> None:
        config = _make_config()
        payload = {"backends": {"echo": {"type": "stdio", "command": "conflict"}}}
        result = import_config(config, payload, conflict_strategy=ConflictStrategy.FAIL)
        assert result.failed_count == 1

    def test_import_dry_run(self) -> None:
        config = _make_config()
        original_keys = set(config.backends.keys())
        payload = {"backends": {"dry-srv": {"type": "stdio", "command": "test"}}}
        result = import_config(config, payload, dry_run=True)
        assert result.added_count == 1
        assert set(config.backends.keys()) == original_keys

    def test_import_registries(self) -> None:
        config = _make_config()
        payload = {"registries": [{"name": "new-reg", "url": "https://new.example.com"}]}
        result = import_config(config, payload, entity_types={"registries"})
        assert result.added_count >= 1

    def test_import_feature_flags(self) -> None:
        config = _make_config()
        payload = {"feature_flags": {"new_flag": True}}
        result = import_config(config, payload, entity_types={"feature_flags"})
        assert result.success

    def test_import_bulk_limit_backends(self) -> None:
        config = _make_config()
        payload = {
            "backends": {f"srv-{i}": {"type": "stdio", "command": "echo"} for i in range(250)}
        }
        result = import_config(config, payload, max_backends=200)
        assert len(result.errors) > 0
        assert "Too many backends" in result.errors[0]


# Metadata provenance tests


class TestMetadataProvenance:
    """Tests for the MetadataProvenance mixin."""

    def test_provenance_fields_optional(self) -> None:
        cfg = StdioBackendConfig(type="stdio", command="echo")
        assert cfg.created_by is None
        assert cfg.updated_by is None
        assert cfg.created_via is None
        assert cfg.updated_via is None
        assert cfg.import_batch_id is None
        assert cfg.metadata_version is None

    def test_provenance_fields_set(self) -> None:
        cfg = StdioBackendConfig(
            type="stdio",
            command="echo",
            created_by="user@example.com",
            created_via="import",
            import_batch_id="abc123",
            metadata_version=1,
        )
        assert cfg.created_by == "user@example.com"
        assert cfg.created_via == "import"
        assert cfg.import_batch_id == "abc123"
        assert cfg.metadata_version == 1

    def test_provenance_on_sse_backend(self) -> None:
        cfg = SseBackendConfig(type="sse", url="https://example.com/mcp", created_via="api")
        assert cfg.created_via == "api"
        assert isinstance(cfg, MetadataProvenance)

    def test_provenance_on_streamable_http_backend(self) -> None:
        cfg = StreamableHttpBackendConfig(
            type="streamable-http", url="https://example.com/mcp", created_via="cli"
        )
        assert cfg.created_via == "cli"
        assert isinstance(cfg, MetadataProvenance)

    def test_provenance_on_registry_entry(self) -> None:
        cfg = RegistryEntryConfig(
            name="test",
            url="https://registry.example.com",
            created_via="tui",
        )
        assert cfg.created_via == "tui"
        assert isinstance(cfg, MetadataProvenance)

    def test_metadata_version_ge_1(self) -> None:
        with pytest.raises(ValidationError):
            StdioBackendConfig(type="stdio", command="echo", metadata_version=0)

    def test_provenance_serializes(self) -> None:
        cfg = StdioBackendConfig(
            type="stdio",
            command="echo",
            created_via="import",
            import_batch_id="batch1",
        )
        data = cfg.model_dump()
        assert data["created_via"] == "import"
        assert data["import_batch_id"] == "batch1"

    def test_backward_compat_no_provenance_fields(self) -> None:
        """Configs without provenance fields still validate."""
        cfg = StdioBackendConfig.model_validate({"type": "stdio", "command": "echo"})
        assert cfg.command == "echo"
        assert cfg.created_by is None


# Catalog service tests


class TestParseCatalog:
    """Tests for catalog YAML/JSON parsing."""

    def test_parse_servers_dict(self) -> None:
        raw = """
servers:
  my-echo:
    transport: stdio
    command: echo
    args: [hello]
  my-sse:
    transport: sse
    url: https://example.com/mcp
"""
        entries = parse_catalog(raw)
        assert len(entries) == 2
        names = {e.name for e in entries}
        assert "my-echo" in names
        assert "my-sse" in names

    def test_parse_flat_dict(self) -> None:
        raw = """
my-echo:
  transport: stdio
  command: echo
"""
        entries = parse_catalog(raw)
        assert len(entries) == 1
        assert entries[0].name == "my-echo"

    def test_parse_list_format(self) -> None:
        raw = """
- name: echo-1
  transport: stdio
  command: echo
- name: echo-2
  transport: stdio
  command: echo2
"""
        entries = parse_catalog(raw)
        assert len(entries) == 2

    def test_parse_empty(self) -> None:
        entries = parse_catalog("")
        assert entries == []

    def test_parse_oversized_raises(self) -> None:
        huge = "x" * (11 * 1024 * 1024)
        with pytest.raises(CatalogParseError, match="exceeds maximum size"):
            parse_catalog(huge)

    def test_parse_invalid_yaml_raises(self) -> None:
        with pytest.raises(CatalogParseError, match="Invalid YAML"):
            parse_catalog("{: bad: yaml: [}")

    def test_parse_non_mapping_raises(self) -> None:
        with pytest.raises(CatalogParseError, match="mapping or list"):
            parse_catalog("42")

    def test_parse_entry_transport_default(self) -> None:
        raw = """
echo-srv:
  command: echo
"""
        entries = parse_catalog(raw)
        assert entries[0].transport == "stdio"

    def test_parse_entry_with_groups(self) -> None:
        raw = """
grouped-srv:
  command: echo
  groups: [dev, test]
"""
        entries = parse_catalog(raw)
        assert entries[0].groups == ["dev", "test"]


class TestStageCatalog:
    """Tests for catalog staging (dry-run preview)."""

    def test_stage_new_entries(self) -> None:
        entries = [
            CatalogEntry(name="srv1", transport="stdio", command="echo"),
            CatalogEntry(name="srv2", transport="sse", url="https://example.com/mcp"),
        ]
        config = _make_config()
        result = stage_catalog(entries, config)
        assert result.dry_run is True
        assert result.staged_count == 2
        assert result.failed_count == 0

    def test_stage_skips_existing(self) -> None:
        entries = [
            CatalogEntry(name="echo", transport="stdio", command="echo"),
        ]
        config = _make_config()
        result = stage_catalog(entries, config)
        assert result.skipped_count == 1

    def test_stage_does_not_skip_when_disabled(self) -> None:
        entries = [
            CatalogEntry(name="echo", transport="stdio", command="echo_new"),
        ]
        config = _make_config()
        result = stage_catalog(entries, config, skip_existing=False)
        assert result.staged_count == 1

    def test_stage_invalid_entry(self) -> None:
        entries = [
            CatalogEntry(name="bad-srv", transport="stdio"),  # no command
        ]
        config = _make_config()
        result = stage_catalog(entries, config)
        assert result.failed_count == 1

    def test_stage_exceeds_max_entries(self) -> None:
        entries = [
            CatalogEntry(name=f"srv-{i}", transport="stdio", command="echo") for i in range(10)
        ]
        config = _make_config()
        result = stage_catalog(entries, config, max_entries=5)
        assert result.failed_count == 10

    def test_stage_no_mutations(self) -> None:
        entries = [
            CatalogEntry(name="new-srv", transport="stdio", command="echo"),
        ]
        config = _make_config()
        original_keys = set(config.backends.keys())
        stage_catalog(entries, config)
        assert set(config.backends.keys()) == original_keys


class TestCommitCatalog:
    """Tests for catalog commit (apply to config)."""

    def test_commit_adds_backends(self) -> None:
        entries = [
            CatalogEntry(name="new-srv", transport="stdio", command="echo"),
        ]
        config = _make_config()
        result = commit_catalog(entries, config)
        assert result.added_count == 1
        assert "new-srv" in config.backends

    def test_commit_skips_existing(self) -> None:
        entries = [
            CatalogEntry(name="echo", transport="stdio", command="echo"),
        ]
        config = _make_config()
        result = commit_catalog(entries, config)
        assert result.skipped_count == 1

    def test_commit_multiple_types(self) -> None:
        entries = [
            CatalogEntry(name="stdio-srv", transport="stdio", command="echo"),
            CatalogEntry(name="sse-srv", transport="sse", url="https://a.com/mcp"),
            CatalogEntry(
                name="http-srv",
                transport="streamable-http",
                url="https://b.com/mcp",
            ),
        ]
        config = ArgusConfig()
        result = commit_catalog(entries, config)
        assert result.added_count == 3
        assert isinstance(config.backends["stdio-srv"], StdioBackendConfig)
        assert isinstance(config.backends["sse-srv"], SseBackendConfig)
        assert isinstance(config.backends["http-srv"], StreamableHttpBackendConfig)

    def test_commit_sets_provenance(self) -> None:
        entries = [
            CatalogEntry(name="prov-srv", transport="stdio", command="echo"),
        ]
        config = ArgusConfig()
        _result = commit_catalog(entries, config, catalog_id="test-batch")
        backend = config.backends["prov-srv"]
        assert backend.created_via == "catalog"
        assert backend.import_batch_id == "test-batch"

    def test_commit_health_check_pass(self) -> None:
        entries = [
            CatalogEntry(name="healthy-srv", transport="stdio", command="echo"),
        ]
        config = ArgusConfig()
        result = commit_catalog(entries, config, health_check=lambda name, cfg: True)
        assert result.added_count == 1

    def test_commit_health_check_fail(self) -> None:
        entries = [
            CatalogEntry(name="unhealthy-srv", transport="stdio", command="echo"),
        ]
        config = ArgusConfig()
        result = commit_catalog(entries, config, health_check=lambda name, cfg: False)
        assert result.added_count == 0
        failed = [i for i in result.items if i.status == CatalogEntryStatus.HEALTH_FAILED]
        assert len(failed) == 1

    def test_commit_health_check_exception(self) -> None:
        def bad_check(name: str, cfg: Any) -> bool:
            raise RuntimeError("check failed")

        entries = [
            CatalogEntry(name="err-srv", transport="stdio", command="echo"),
        ]
        config = ArgusConfig()
        result = commit_catalog(entries, config, health_check=bad_check)
        assert result.added_count == 0

    def test_commit_invalid_transport(self) -> None:
        entries = [
            CatalogEntry(name="bad-srv", transport="websocket", url="ws://a.com"),
        ]
        config = ArgusConfig()
        result = commit_catalog(entries, config)
        assert result.failed_count == 1

    def test_commit_exceeds_max_entries(self) -> None:
        entries = [
            CatalogEntry(name=f"srv-{i}", transport="stdio", command="echo") for i in range(10)
        ]
        config = ArgusConfig()
        result = commit_catalog(entries, config, max_entries=5)
        assert result.failed_count == 10
        assert len(config.backends) == 0

    def test_commit_catalog_result_summary(self) -> None:
        entries = [
            CatalogEntry(name="srv1", transport="stdio", command="echo"),
        ]
        config = ArgusConfig()
        result = commit_catalog(entries, config)
        summary = result.summary()
        assert "added=1" in summary
        assert "catalog=" in summary


# Round-trip tests


class TestExportImportRoundTrip:
    """Test export → import round-trip preserves configuration."""

    def test_round_trip_backends(self) -> None:
        config = _make_config()
        exported = export_config(config, secret_handling=SecretHandling.PRESERVE)
        target = ArgusConfig()
        result = import_config(target, exported.data)
        assert result.success
        assert "echo" in target.backends
        assert "web" in target.backends

    def test_round_trip_with_strip_loses_secrets(self) -> None:
        config = _make_config_with_secrets()
        exported = export_config(config, secret_handling=SecretHandling.STRIP)
        target = ArgusConfig()
        result = import_config(target, exported.data)
        assert result.success
