# Test Coverage Gaps Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` (160 files, 28,965 lines) vs `tests/` (56 test files, ~50 test functions collected)

---

## Module-to-Test Mapping

### Covered Modules (have dedicated test files)

| Module | Test File | Assessment |
|--------|-----------|------------|
| `server/app.py` | `test_app_server.py` | Covered |
| `audit/logger.py` | `test_audit.py` | Covered |
| `bridge/auth/pkce.py` | `test_auth_pkce.py` | Covered |
| `server/auth/` | `test_auth.py`, `test_oidc.py` | Covered |
| `bridge/capability_registry.py` | `test_capability_registry_new.py` | Covered |
| `bridge/health/checker.py` | `test_health_checker.py`, `test_circuit_breaker.py` | Covered |
| `config/diff.py` | `test_config_diff.py` | Covered |
| `config/watcher.py` | `test_config_hotreload.py` | Covered |
| `config/schema*.py` | `test_config_schemas.py`, `test_config_migration.py` | Covered |
| `bridge/conflict.py` | `test_conflict.py` | Covered |
| `constants.py` | `test_constants.py` | Covered |
| `bridge/container/` | `test_container.py`, `test_templates.py` | Covered |
| `display/console.py` | `test_display_console.py` | Covered |
| `display/installer.py` | `test_display_installer.py` | Covered |
| `display/logging_config.py` | `test_display_logging.py` | Covered |
| `bridge/elicitation.py` | `test_elicitation.py` | Covered |
| `errors.py` | `test_errors.py` | Covered |
| `bridge/filter.py` | `test_filter.py` | Covered |
| `config/flags.py` | `test_flags_yaml_clientgen.py` | Covered |
| `bridge/groups.py` | `test_groups.py` | Covered |
| `server/handlers.py` | `test_handlers_new.py` | Covered |
| `bridge/middleware/` | `test_middleware*.py` (4 files) | Covered |
| `server/management/` | `test_mgmt_auth.py`, `test_mgmt_router.py`, `test_management_schemas.py` | Covered |
| `bridge/optimizer/` | `test_optimizer.py` | Covered |
| `server/auth/` | `test_phase4_security.py` | Covered |
| `registry/` | `test_registry.py` | Covered |
| `bridge/rename.py` | `test_rename.py` | Covered |
| `runtime/models.py` | `test_runtime_models.py` | Covered |
| `secrets/` | `test_secrets.py` | Covered |
| `server/session/` | `test_session.py`, `test_session_models.py` | Covered |
| `sessions.py` | `test_sessions.py` | Covered |
| `bridge/client_manager.py` | `test_staggered_startup.py` | Partially covered |
| `server/transport.py` | `test_transport.py` | Covered |
| `tui/server_manager.py` | `test_tui_server_manager.py` | Covered |
| `tui/settings.py` | `test_tui_settings.py` | Covered |
| `bridge/version_checker.py` | `test_version_checker.py` | Covered |
| `server/lifespan.py` | `test_wiring.py` | Partially covered |
| `workflows/` | `test_workflows.py` | Covered |

---

### UNCOVERED Modules (no dedicated test file)

### [HIGH] cli.py -- No test file

- **File:** `argus_mcp/cli.py` (943 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** The main CLI entry point with subcommands (`server`, `stop`, `status`, `tui`, `build`, `secret`) has no test file. Contains signal handling, process management, subprocess spawning, and terminal restoration -- all of which are error-prone.
- **Suggested fix:** Create `test_cli.py` with unit tests for `_find_config_file`, `_build_parser`, `_write_pid_file`, `_remove_pid_file`, and integration tests for subcommand dispatch.

### [HIGH] runtime/service.py -- No dedicated test file

- **File:** `argus_mcp/runtime/service.py` (849 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** `ArgusService` manages the full lifecycle (start/stop/reload/reconnect) with a state machine, event system, and health checker integration. Only partially tested via `test_wiring.py`.
- **Suggested fix:** Create `test_service.py` testing state transitions, reload logic, event emission, and error handling.

### [HIGH] tui/app.py -- No test file

- **File:** `argus_mcp/tui/app.py` (958 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** The main TUI application with polling, connection management, and 20+ event handlers is completely untested.
- **Suggested fix:** Create `test_tui_app.py` using Textual's `App.run_test()` framework.

### [HIGH] bridge/auth/store.py -- No test file

- **File:** `argus_mcp/bridge/auth/store.py` (173 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** Token persistence with file I/O, chmod, and expiry checking. Security-critical module handling OAuth tokens.
- **Suggested fix:** Create `test_auth_store.py` testing save/load/expiry/delete with tmpdir fixtures.

### [HIGH] bridge/auth/discovery.py -- No test file

- **File:** `argus_mcp/bridge/auth/discovery.py` (339 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** OAuth discovery (well-known endpoints, DCR) -- security-critical.
- **Suggested fix:** Create `test_auth_discovery.py` testing endpoint resolution, error handling, and caching.

### [MEDIUM] bridge/auth/provider.py -- No test file

- **File:** `argus_mcp/bridge/auth/provider.py` (336 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** OAuth token management and refresh logic.
- **Suggested fix:** Create `test_auth_provider.py` testing token acquisition, refresh, and expiry handling.

### [MEDIUM] bridge/container/image_builder.py -- No dedicated test

- **File:** `argus_mcp/bridge/container/image_builder.py` (412 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** Container image building with Dockerfile generation and docker/podman CLI interaction. Partially tested via `test_container.py`.
- **Suggested fix:** Create dedicated `test_image_builder.py` testing Dockerfile generation, build argument handling, and error paths.

### [MEDIUM] bridge/container/wrapper.py -- No dedicated test

- **File:** `argus_mcp/bridge/container/wrapper.py` (462 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** Container wrapping logic that transforms stdio params into container-based execution.

### [MEDIUM] bridge/container/runtime.py -- No dedicated test

- **File:** `argus_mcp/bridge/container/runtime.py` (742 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** Container runtime detection and management. One of the largest modules without dedicated tests.

### [MEDIUM] bridge/container/network.py -- No dedicated test

- **File:** `argus_mcp/bridge/container/network.py` (71 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests

### [MEDIUM] config/loader.py -- No dedicated test

- **File:** `argus_mcp/config/loader.py` (271 lines)
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** Config loading with YAML parsing, secret resolution, and backend parameter construction. Partially exercised by other tests but deserves its own test file.

### [MEDIUM] server/lifespan.py -- Minimally tested

- **File:** `argus_mcp/server/lifespan.py` (659 lines)
- **Tool:** Manual file inspection
- **Rule:** insufficient-tests
- **Description:** Core server lifecycle management with 20+ deferred imports, monkey-patching, and complex initialization. Only partially tested via `test_wiring.py` (26 tests).

### [MEDIUM] bridge/client_manager.py -- Minimally tested

- **File:** `argus_mcp/bridge/client_manager.py` (1,757 lines)
- **Tool:** Manual file inspection
- **Rule:** insufficient-tests
- **Description:** The largest file in the codebase with a CC=44 god function (`start_all`). Only tested via `test_staggered_startup.py` (10 tests) which covers only the staggered startup feature, not the overall manager lifecycle.

### [MEDIUM] All TUI screens untested

- **Files:** `tui/screens/dashboard.py`, `tui/screens/tools.py`, `tui/screens/registry.py`, `tui/screens/skills.py`, `tui/screens/settings.py`, `tui/screens/setup_wizard.py`, `tui/screens/health.py`, `tui/screens/security.py`, `tui/screens/operations.py`, `tui/screens/audit_log.py`, `tui/screens/tool_editor.py`, `tui/screens/client_config.py`, `tui/screens/backend_detail.py`, `tui/screens/theme_picker.py`, `tui/screens/exit_modal.py`, `tui/screens/elicitation.py`, `tui/screens/server_detail.py`
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** 17 TUI screens with no test coverage. These contain complex UI state management, data transformation, and API interactions.

### [LOW] All TUI widgets untested

- **Files:** 20+ widget files in `tui/widgets/`
- **Tool:** Manual file inspection
- **Rule:** missing-tests
- **Description:** Backend status, capability tables, event log, health panel, optimizer panel, sessions panel, workflows panel, and 13+ other widgets.

### [LOW] server/origin.py -- No test

- **File:** `argus_mcp/server/origin.py`
- **Rule:** missing-tests

### [LOW] config/client_gen.py -- No test

- **File:** `argus_mcp/config/client_gen.py`
- **Rule:** missing-tests

### [LOW] telemetry/ -- No tests

- **Files:** `telemetry/config.py`, `telemetry/tracing.py`, `telemetry/metrics.py`
- **Rule:** missing-tests

### [LOW] skills/ -- No tests

- **Files:** `skills/manager.py`, `skills/manifest.py`
- **Rule:** missing-tests

### [LOW] _task_utils.py -- No test

- **File:** `argus_mcp/_task_utils.py`
- **Rule:** missing-tests

### [LOW] tui/api_client.py -- No test

- **File:** `argus_mcp/tui/api_client.py`
- **Rule:** missing-tests

### [LOW] tui/events.py -- No test

- **File:** `argus_mcp/tui/events.py`
- **Rule:** missing-tests

---

## Security-Critical Untested Modules

| Module | Risk | Reason |
|--------|------|--------|
| `bridge/auth/store.py` | HIGH | Handles OAuth token persistence with file permissions |
| `bridge/auth/discovery.py` | HIGH | Handles OAuth endpoint discovery, SSRF surface |
| `bridge/auth/provider.py` | HIGH | Handles token refresh and credential management |
| `cli.py` | HIGH | Process management, signal handling, PID files |
| `secrets/providers.py` | MEDIUM | File encryption, keyring (partially tested via `test_secrets.py`) |
| `bridge/container/runtime.py` | MEDIUM | Container privilege management |

---

## Test Infrastructure Notes

- **Test runner:** pytest with `tests/conftest.py` for shared fixtures
- **Test count:** ~50 test functions collected (excluding integration tests)
- **Test files:** 56 files in `tests/` directory
- **Cassettes:** VCR cassettes in `tests/cassettes/` for HTTP replay
- **Scenarios:** `tests/scenarios.yml` for test scenario configuration
- **Integration tests:** Marked with `@pytest.mark.integration`, excluded from default run

---

## Summary

| Category | Count |
|----------|-------|
| Modules with dedicated tests | 37 |
| Modules without tests (HIGH priority) | 5 |
| Modules without tests (MEDIUM priority) | 10 |
| Modules without tests (LOW priority) | 25+ |
| TUI screens untested | 17 |
| TUI widgets untested | 20+ |
| Security-critical untested | 6 |
| Total test functions | ~50 (non-integration) |
| **Test coverage gap estimate** | **~45% of modules lack dedicated tests** |
