# Modularity & Complexity Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI (159+ files, ~29K lines)
**Tools:** Radon CC (v6.0.1), Radon MI (v6.0.1), Manual inspection

---

## Files Exceeding 500 Lines

| File | Lines | Assessment |
|------|-------|------------|
| `bridge/client_manager.py` | 1,757 | God object -- MI grade C (2.27) |
| `tui/app.py` | 958 | TUI application root -- many event handlers |
| `cli.py` | 943 | Large but sectioned by subcommand |
| `runtime/service.py` | 849 | Lifecycle state machine + event system |
| `tui/screens/setup_wizard.py` | 746 | 4 internal classes, reasonable separation |
| `bridge/container/runtime.py` | 742 | Container runtime management |
| `tui/screens/settings.py` | 697 | Multi-tab settings, large compose methods |
| `server/lifespan.py` | 659 | Signal handling + monkey-patching + lifecycle |
| `tui/widgets/workflows_panel.py` | 596 | Complex workflow execution widget |
| `display/installer.py` | 582 | Rich progress display with build output |
| `server/management/router.py` | 533 | 11 API endpoints in one file |
| `tui/screens/skills.py` | 504 | Skill discovery + apply flow |
| `bridge/container/wrapper.py` | 462 | Container wrapping logic |
| `bridge/container/templates/_generators.py` | 457 | Template generation |

---

## Radon Cyclomatic Complexity -- Grade D (High)

### [HIGH] CapabilityRegistry._discover_caps_by_type() -- CC=29

- **File:** `argus_mcp/bridge/capability_registry.py:59`
- **Tool:** Radon CC
- **Rule:** CC=29, Grade D
- **Description:** Discovery with filtering, renaming, conflict resolution, and timeout handling all in one method. 198 lines of deeply nested logic.
- **Evidence:** `uv run python -m radon cc argus_mcp/bridge/capability_registry.py -s -n C` reports CC=29.
- **Suggested fix:** Break into `_filter_capabilities()`, `_rename_capabilities()`, and `_register_capabilities()` phases.

### [HIGH] InstallerDisplay.update() -- CC=25

- **File:** `argus_mcp/display/installer.py:425`
- **Tool:** Radon CC
- **Rule:** CC=25, Grade D
- **Description:** Phase-specific display updates with different progress bar styling for each phase. 96 lines with many branches.
- **Evidence:** `uv run python -m radon cc argus_mcp/display/installer.py -s -n C` reports CC=25.
- **Suggested fix:** Use a dispatch table mapping phases to update methods.

### [HIGH] ToolsScreen.on_input_changed() -- CC=23

- **File:** `argus_mcp/tui/screens/tools.py:114`
- **Tool:** Radon CC
- **Rule:** CC=23, Grade D
- **Description:** Live search filtering with multi-field matching across tool name, description, backend, and annotations.
- **Evidence:** `uv run python -m radon cc argus_mcp/tui/screens/tools.py -s -n C` reports CC=23.
- **Suggested fix:** Extract filtering logic to a pure function.

### [HIGH] _cmd_stop() -- CC=22

- **File:** `argus_mcp/cli.py:343`
- **Tool:** Radon CC
- **Rule:** CC=22, Grade D
- **Description:** Handles 4 different code paths: named session stop, single session auto-detect, multiple sessions error, and legacy PID file fallback.
- **Suggested fix:** Extract `_stop_by_name()`, `_stop_by_pid_file()`.

### [HIGH] app_lifespan() -- CC=22

- **File:** `argus_mcp/server/lifespan.py:412`
- **Tool:** Radon CC
- **Rule:** CC=22, Grade D
- **Description:** Startup display, service start, monkey-patching, session manager creation, and three separate exception handlers.
- **Suggested fix:** Extract display setup, session manager setup, and error handling.

### [HIGH] ArgusService._build_registry() -- CC=22

- **File:** `argus_mcp/runtime/service.py:178`
- **Tool:** Radon CC
- **Rule:** CC=22, Grade D
- **Description:** Builds filters, rename maps, and cap_fetch timeouts from config in a single method with 63 lines.
- **Suggested fix:** Extract `_build_filters()`, `_build_rename_maps()`, `_build_timeouts()`.

### [HIGH] SkillsScreen.action_apply_skill() -- CC=20

- **File:** `argus_mcp/tui/screens/skills.py:326`
- **Tool:** Radon CC
- **Rule:** CC=20, Grade D
- **Description:** Skill application with config merge, backend addition, and hot-reload.
- **Suggested fix:** Extract config merge and backend setup.

### [HIGH] _cmd_tui() -- CC=20

- **File:** `argus_mcp/cli.py:485`
- **Tool:** Radon CC
- **Rule:** CC=20, Grade C
- **Description:** Config loading, URL normalization, server manager creation, and terminal restoration in one function.
- **Suggested fix:** Extract config resolution and server manager setup.

### [HIGH] _manage_subproc() -- CC=19

- **File:** `argus_mcp/bridge/client_manager.py:80`
- **Tool:** Radon CC
- **Rule:** CC=19, Grade C
- **Description:** Subprocess lifecycle management with stdout/stderr tee-ing, signal forwarding, and cleanup.
- **Suggested fix:** Extract I/O tee logic into a helper.

### [HIGH] ClientManager._retry_failed_backends() -- CC=18

- **File:** `argus_mcp/bridge/client_manager.py:1040`
- **Tool:** Radon CC
- **Rule:** CC=18, Grade C
- **Description:** Retry loop with exponential backoff, semaphore gating, staggered concurrency, and auth discovery integration.
- **Suggested fix:** Simplify by extracting `_gated_retry()` as a standalone coroutine.

---

## Radon Cyclomatic Complexity -- Grade C (40+ functions)

The following is a summary of all CC grade-C functions (CC 11-19):

| Function | CC | File |
|----------|----|------|
| `gen_status_info()` | 18 | `display/console.py:22` |
| `BearerAuthMiddleware.__call__()` | 17 | `server/management/auth.py:93` |
| `InstallerDisplay.render_initial()` | 17 | `display/installer.py:333` |
| `BackendStatusWidget._refresh_display()` | 17 | `tui/widgets/backend_status.py:96` |
| `CapabilitySection.populate()` | 17 | `tui/widgets/capability_tables.py:100` |
| `ClientManager.stop_all()` | 17 | `bridge/client_manager.py:1225` |
| `configs_differ()` | 16 | `config/diff.py:32` |
| `disp_console_status()` | 16 | `display/console.py:82` |
| `HealthPanel.update_from_backends()` | 16 | `tui/widgets/health_panel.py:166` |
| `_discover_oidc()` | 15 | `bridge/auth/discovery.py:248` |
| `_attach_to_mcp_server()` | 15 | `server/lifespan.py:131` |
| `wrap_backend()` | 15 | `bridge/container/wrapper.py:55` |
| `AuditLogScreen._apply_filters()` | 15 | `tui/screens/audit_log.py:131` |
| `SkillsScreen._apply_filter()` | 15 | `tui/screens/skills.py:214` |
| `_backend_to_dict()` | 14 | `config/loader.py:87` |
| `parse_uvx_args()` | 14 | `bridge/container/templates/_generators.py:42` |
| `ClientManager._try_auth_discovery()` | 14 | `bridge/client_manager.py:1481` |
| `ClientManager._await_auth_discoveries()` | 14 | `bridge/client_manager.py:987` |
| `ServerGroupsWidget.update_groups()` | 14 | `tui/widgets/server_groups.py:57` |
| `OptimizerPanel._do_test_search()` | 14 | `tui/widgets/optimizer_panel.py:162` |
| `_BackendBuilderPanel._copy_to_editor()` | 14 | `tui/screens/setup_wizard.py:507` |
| `handle_backends()` | 13 | `server/management/router.py:150` |
| `detect_runtime()` | 13 | `display/installer.py:56` |
| `InstallerDisplay.finalize()` | 13 | `display/installer.py:524` |
| `ElicitationFormWidget.compose()` | 13 | `tui/widgets/elicitation_form.py:53` |
| `SkillsScreen._update_detail()` | 13 | `tui/screens/skills.py:262` |
| `RoutingMiddleware.__call__()` | 12 | `bridge/middleware/routing.py:34` |
| `ToolIndex._populate()` | 12 | `bridge/optimizer/search.py:100` |
| `ClientManager._start_backend_svr()` | 12 | `bridge/client_manager.py:510` |
| `SettingsScreen.on_button_pressed()` | 12 | `tui/screens/settings.py:422` |
| `ServerDetailModal.compose()` | 12 | `tui/screens/server_detail.py:77` |
| `ToolsScreen._update_status_bar()` | 12 | `tui/screens/tools.py:87` |
| `InstallPanelWidget._update_detail()` | 12 | `tui/widgets/install_panel.py:82` |
| `ElicitationFormWidget._collect_data()` | 12 | `tui/widgets/elicitation_form.py:107` |
| `VersionDriftPanel.update_versions()` | 12 | `tui/widgets/version_drift.py:63` |
| `ClientManager._apply_network_env()` | 11 | `bridge/client_manager.py:288` |
| `ClientManager.start_all()` | 11 | `bridge/client_manager.py:1142` |
| `CapabilityRegistry.remove_backend()` | 11 | `bridge/capability_registry.py:356` |
| `create_auth_provider()` | 11 | `bridge/auth/provider.py:274` |
| `setup_logging()` | 11 | `display/logging_config.py:137` |
| `BackendDetailModal.compose()` | 11 | `tui/screens/backend_detail.py:82` |
| `_discover_workflow_yamls()` | 11 | `tui/widgets/workflows_panel.py:56` |
| `ArgusApp._poll_once()` | 11 | `tui/app.py:473` |
| `ArgusApp._apply_status_response()` | 11 | `tui/app.py:536` |
| `ArgusService.reload()` | 11 | `runtime/service.py:472` |
| `_BackendBuilderPanel._generate_snippet()` | 11 | `tui/screens/setup_wizard.py:485` |
| `ToolEditorScreen.action_save_changes()` | 11 | `tui/screens/tool_editor.py:237` |
| `ToolEditorScreen._update_diff_panel()` | 11 | `tui/screens/tool_editor.py:331` |

---

## Radon Maintainability Index -- Grade C

### [CRITICAL] client_manager.py -- MI=2.27

- **File:** `argus_mcp/bridge/client_manager.py`
- **Tool:** Radon MI
- **Rule:** Grade C (2.27 on 0-100 scale)
- **Description:** This is an extremely low MI score. Grade C (below 10) indicates a module that is very difficult to maintain. The 1,757-line file combines connection management, container wrapping, auth discovery, progress reporting, retry logic, subprocess management, and shutdown cleanup. The `start_all()` method was refactored from its previous CC=44 extreme to CC=11 by extracting methods, but the module itself remains oversized.
- **Evidence:** `uv run python -m radon mi argus_mcp/ -s -n C` reports only `client_manager.py` at grade C (2.27).
- **Suggested fix:** Split into:
  - `client_manager.py` -- orchestration only (start_all, stop_all)
  - `backend_connection.py` -- per-backend connect/disconnect
  - `startup_coordinator.py` -- staggered startup with retry
  - `transport_factory.py` -- stdio/SSE/HTTP transport creation

---

## Classes with >7 Methods

| Class | Methods | File |
|-------|---------|------|
| `ClientManager` | 25+ | `bridge/client_manager.py` |
| `ArgusApp` | 20+ | `tui/app.py` |
| `ArgusService` | 15+ | `runtime/service.py` |
| `SettingsScreen` | 12+ | `tui/screens/settings.py` |
| `InstallerDisplay` | 10+ | `display/installer.py` |
| `SkillsScreen` | 10+ | `tui/screens/skills.py` |
| `CapabilityRegistry` | 10+ | `bridge/capability_registry.py` |
| `SetupWizardScreen` | 8+ | `tui/screens/setup_wizard.py` |

---

## Functions Exceeding 40 Lines

| Function | ~Lines | File |
|----------|--------|------|
| `app_lifespan()` | ~250 | `server/lifespan.py:412` |
| `_start_backend_svr()` | ~77 | `bridge/client_manager.py:510` |
| `_connect_backend()` (now inside _start_backend_svr) | ~60 | `bridge/client_manager.py` |
| `_retry_failed_backends()` | ~100 | `bridge/client_manager.py:1040` |
| `start_all()` | ~82 | `bridge/client_manager.py:1142` |
| `stop_all()` | ~82 | `bridge/client_manager.py:1225` |
| `handle_backends()` | ~78 | `server/management/router.py:150` |
| `_cmd_stop()` | ~108 | `cli.py:343` |
| `_cmd_tui()` | ~84 | `cli.py:485` |
| `_build_registry()` | ~63 | `runtime/service.py:178` |
| `InstallerDisplay.update()` | ~96 | `display/installer.py:425` |
| `_attach_to_mcp_server()` | ~145 | `server/lifespan.py:131` |
| `_manage_subproc()` | ~115 | `bridge/client_manager.py:80` |
| `_discover_caps_by_type()` | ~198 | `bridge/capability_registry.py:59` |

---

## Notable Improvements Since Previous Audit

1. **`start_all()` CC reduced from 44 to 11** -- The method was decomposed into `_launch_remote_backends()`, `_build_and_connect_stdio()`, `_gather_remote_results()`, and `_retry_failed_backends()`.
2. **`handle_backends()` CC reduced from 21 to 13** -- Capability counting was extracted into the `_count_by_backend()` inner helper.
3. **`_start_backend_svr()` CC reduced from 27 to 12** -- Transport-specific logic was streamlined.

---

## Summary

| Metric | Count |
|--------|-------|
| Files >500 lines | 14 |
| Functions >40 lines | 14 |
| Classes >7 methods | 8 |
| CC Grade D (CC >= 20) | 8 |
| CC Grade C (CC 11-19) | 48 |
| MI Grade C (critical) | 1 |
| **Total modularity findings** | **93** |
