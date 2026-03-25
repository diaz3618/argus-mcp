# TUI Screens Reference

> **Source location:** All TUI source files live in
> `packages/argus_cli/argus_cli/tui/`. The legacy `argus_mcp/tui/` tree
> contains the server-package copy; the argus-cli tree is the actively
> developed version with all Phase 2–5 enhancements described below.

## Screen Architecture

All screens extend `ArgusScreen` (a common `BaseScreen`) and implement
`compose_content()` for layout. The TUI uses Textual's mode system — each
screen is registered as a mode in `ArgusApp`.

```
ArgusApp
├── DashboardScreen       (mode: "dashboard",       key: 1/d)
├── ToolsScreen           (mode: "tools",            key: 2)
├── RegistryScreen        (mode: "registry",         key: 3)
├── SettingsScreen        (mode: "settings",         key: 4/s)
├── SkillsScreen          (mode: "skills",           key: 5)
├── ToolEditorScreen      (mode: "editor",           key: 6)
├── AuditLogScreen        (mode: "audit",            key: 7)
├── HealthScreen          (mode: "health",           key: 8/h)
├── SecurityScreen        (mode: "security",         key: 9)
├── OperationsScreen      (mode: "operations",       key: 0/o)
├── ContainersScreen      (mode: "containers",       key: c)
├── KubernetesScreen      (mode: "kubernetes",       key: k)
│
├── BackendConfigModal    (modal — backend installation form)
├── BackendDetailModal    (modal — lifecycle status for a backend)
├── ServerDetailModal     (modal — registry server detail / install)
├── CatalogBrowserScreen  (screen — catalog import pipeline)
├── ClientConfigScreen    (modal — client-side config editor)
├── ServerLogsScreen      (screen — live server log viewer)
├── ExportImportScreen    (screen — config export/import)
├── SetupWizardScreen     (screen — first-run configuration wizard)
├── ExitModal             (modal — exit confirmation with resume options)
├── ElicitationScreen     (triggered by backends)
└── ThemePickerScreen     (key: T)
```

## DashboardScreen

**File:** `tui/screens/dashboard.py`
**Key:** `1` or `d`

The primary monitoring screen with a grid layout:

```
┌──────────────────────────────────────────────┐
│  Server Selector (multi-server mode only)    │
├──────────────────┬───────────────────────────┤
│                  │                           │
│  Server Info     │  Backend Status           │
│  - Name          │  - Per-backend state      │
│  - Version       │  - Phase (status dots)    │
│  - Uptime        │  - Health indicators      │
│  - Transport     │  - Capability counts      │
│                  │                           │
├──────────────────┴───────────────────────────┤
│                                              │
│  Event Log                                   │
│  - Timestamped events                        │
│  - Severity indicators                       │
│  - Backend attribution                       │
│                                              │
├──────────────────────────────────────────────┤
│  Capability Section (tabbed)                 │
│  - Tools | Resources | Prompts               │
│  - Name, backend, description                │
└──────────────────────────────────────────────┘
```

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `ServerSelectorWidget` | `widgets/server_selector.py` | Multi-server dropdown |
| `ServerInfoWidget` | `widgets/server_info.py` | Server details panel |
| `BackendStatusWidget` | `widgets/backend_status.py` | Backend status grid |
| `EventLogWidget` | `widgets/event_log.py` | Event stream |
| `CapabilitySection` | `widgets/capability_tables.py` | Tabbed capability tables |

## ToolsScreen

**File:** `tui/screens/tools.py`
**Key:** `2`

Full-screen capability explorer with filtering and search.

- Tab switching: `t` (tools), `r` (resources), `p` (prompts)
- Filter toggle for refining results
- Detailed view when selecting a capability
- Tool preview widget for schema inspection

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `FilterToggleWidget` | `widgets/filter_toggle.py` | Filter controls |
| `FilterBar` | `widgets/filter_bar.py` | Inline text filtering |
| `ToolPreviewWidget` | `widgets/tool_preview.py` | Tool schema viewer |
| `CapabilitySection` | `widgets/capability_tables.py` | Capability tables |

## RegistryScreen

**File:** `tui/screens/registry.py`
**Key:** `3`

Server browser for discovering and managing MCP servers.

- Registry browser listing available servers
- Server metadata and details panel
- Install panel for adding new backends

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `RegistryBrowserWidget` | `widgets/registry_browser.py` | Server listing |
| `InstallPanelWidget` | `widgets/install_panel.py` | Backend installation |

## SettingsScreen

**File:** `tui/screens/settings.py`
**Key:** `4` or `s`

Configuration viewer and preferences.

- Current config preview (loaded from server)
- Theme selection
- Application settings

## SkillsScreen

**File:** `tui/screens/skills.py`
**Key:** `5`

Manage installed skill packs:

- List installed skills with enable/disable toggles
- View skill manifests
- Install/uninstall skills

## ToolEditorScreen

**File:** `tui/screens/tool_editor.py`
**Key:** `6`

Edit and test tool parameters:

- Parameter editor with type-aware input fields
- JSON schema visualization
- Test invocation (dry-run)

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `ParamEditorWidget` | `widgets/param_editor.py` | Parameter editing |

## AuditLogScreen

**File:** `tui/screens/audit_log.py`
**Key:** `7`

Extends `BaseLogScreen` (shared log infrastructure with pause/resume, export).

- Timestamped audit events with method, backend, and status columns
- Filter by method type, backend name, or status code
- Expandable detail view with full request/response and timing data

## HealthScreen

**File:** `tui/screens/health.py`
**Key:** `8` or `h`

Backend health monitoring:

- Per-backend health status and history
- Health check configuration and intervals
- Version drift detection across backends

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `HealthPanelWidget` | `widgets/health_panel.py` | Health status display |
| `VersionDriftWidget` | `widgets/version_drift.py` | Version drift indicator |

## SecurityScreen

**File:** `tui/screens/security.py`
**Key:** `9`

Security overview and controls:

- Authentication status and configuration
- Active sessions display
- Middleware chain visualization
- Secrets and network isolation status

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `SecretsPanelWidget` | `widgets/secrets_panel.py` | Secrets management display |
| `SessionsPanelWidget` | `widgets/sessions_panel.py` | Active sessions |
| `NetworkPanelWidget` | `widgets/network_panel.py` | Network isolation status |

## OperationsScreen

**File:** `tui/screens/operations.py`
**Key:** `0` or `o`

Operational controls and management:

- Backend management (reconnect, restart, remove)
- Server groups and sync status
- Workflow management and optimizer controls

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `ServerGroupsWidget` | `widgets/server_groups.py` | Server group management |
| `SyncStatusWidget` | `widgets/sync_status.py` | Config sync status |
| `WorkflowsPanelWidget` | `widgets/workflows_panel.py` | Workflow management |

## ContainersScreen

**File:** `tui/screens/containers.py`
**Key:** `c`

Docker container management via argusd. Tabbed layout with four panes:

- **Overview** — Container list with status, resource usage, uptime
- **Logs** — Multi-container log viewer with severity coloring
- **Stats** — Reactive CPU/memory bars driven by argusd push stream
- **Exec** — Placeholder for interactive terminal (future)

All data flows through `DaemonClient` over the argusd Unix Domain Socket.

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `ContainerTable` | `widgets/container_table.py` | Container list with status |
| `ContainerStatusBar` | `widgets/container_table.py` | Container summary bar |
| `ContainerLogViewer` | `widgets/container_logs.py` | Log stream viewer |
| `ContainerStatsPanel` | `widgets/container_stats.py` | CPU/memory stats |

## KubernetesScreen

**File:** `tui/screens/kubernetes.py`
**Key:** `k`

Kubernetes pod management via argusd. Tabbed layout with four panes:

- **Pods** — Pod list with status, node, IP, restarts, age
- **Logs** — Per-pod log viewer with severity coloring
- **Events** — Kubernetes events for the selected pod
- **Details** — Describe output for the selected pod

Only available when argusd has a Kubernetes connection.

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `PodTable` | `widgets/pod_table.py` | Pod list with status |
| `PodStatusBar` | `widgets/pod_table.py` | Pod summary bar |
| `ContainerLogViewer` | `widgets/container_logs.py` | Log stream (shared widget) |

## BackendConfigModal

**File:** `tui/screens/backend_config.py`
**Access:** Triggered from Registry or Dashboard

Transport-specific backend configuration form. Supports configuring
stdio, SSE, and streamable-http backends with all relevant options.
Used for both registry installs (pre-filled) and custom backend adds.

## BackendDetailModal

**File:** `tui/screens/backend_detail.py`
**Access:** Press Enter on a backend row in the Dashboard

Full lifecycle status for a backend server:

- Phase, conditions log, health metrics, capabilities count
- Actions: restart, disconnect, force health check

## ServerDetailModal

**File:** `tui/screens/server_detail.py`
**Access:** Select a server in the Registry screen

Server metadata from the registry: tools list, version, categories,
and an Install button.

## CatalogBrowserScreen

**File:** `tui/screens/catalog_browser.py`
**Access:** Via command palette or menu

Catalog import pipeline:

- YAML editor for catalog entries
- Dry-run preview table with staging status
- Commit confirmation step

## ClientConfigScreen

**File:** `tui/screens/client_config.py`
**Access:** Via Settings screen

Client-side configuration editor for argus-cli preferences.

## ServerLogsScreen

**File:** `tui/screens/server_logs.py`
**Access:** Via Dashboard or Operations screen

Live server log viewer. Extends `BaseLogScreen` with server-specific
log fetching and filtering.

## ExportImportScreen

**File:** `tui/screens/export_import.py`
**Access:** Via command palette or Settings

Configuration export and import:

- Export current config as YAML
- Import config from file with validation preview

## SetupWizardScreen

**File:** `tui/screens/setup_wizard.py`
**Access:** Triggered on first run or via command palette

Step-by-step configuration wizard for initial setup.

## ExitModal

**File:** `tui/screens/exit_modal.py`
**Access:** Quit action (`q`)

Graceful exit confirmation with options:

- Save state and restore on next launch
- Stop all servers and exit
- Cancel

## ElicitationScreen

**File:** `tui/screens/elicitation.py`
**Access:** Triggered by backends

Handle MCP elicitation protocol requests:

- Displays elicitation form from backend
- Captures user input
- Returns response to the requesting backend

### Widgets Used

| Widget | File | Purpose |
|--------|------|---------|
| `ElicitationFormWidget` | `widgets/elicitation_form.py` | Dynamic form |

## ThemePickerScreen

**File:** `tui/screens/theme_picker.py`
**Key:** `T` (Shift+T)

Visual theme selection:

- Preview of available themes (16 built-in YAML palettes)
- Live preview before applying
- Persistent theme preference

## Widget Reference

| Widget | File | Description |
|--------|------|-------------|
| `BackendStatusWidget` | `backend_status.py` | Backend lifecycle display (uses `design.py` status dots) |
| `CapabilitySection` | `capability_tables.py` | Tabbed tables for tools/resources/prompts |
| `ContainerLogViewer` | `container_logs.py` | Multi-container log stream with severity coloring |
| `ContainerStatsPanel` | `container_stats.py` | Reactive CPU/memory bars |
| `ContainerTable` | `container_table.py` | Container list with status, uptime, resources |
| `ContainerStatusBar` | `container_table.py` | Container summary (running/stopped counts) |
| `ElicitationFormWidget` | `elicitation_form.py` | Dynamic elicitation form |
| `EventLogWidget` | `event_log.py` | Scrollable event timeline |
| `FilterBar` | `filter_bar.py` | Inline text filtering input |
| `FilterToggleWidget` | `filter_toggle.py` | Capability filter controls |
| `HealthPanelWidget` | `health_panel.py` | Per-backend health status and history |
| `InstallPanelWidget` | `install_panel.py` | Backend installation form |
| `JumpOverlay` | `jump_overlay.py` | Jump-mode label overlay for keyboard navigation |
| `MiddlewarePanelWidget` | `middleware_panel.py` | Middleware chain visualization |
| `ModuleContainer` | `module_container.py` | Collapsible container for modular screen sections |
| `NetworkPanelWidget` | `network_panel.py` | Network isolation status |
| `OptimizerPanelWidget` | `optimizer_panel.py` | Optimizer controls and metrics |
| `OtelPanelWidget` | `otel_panel.py` | OpenTelemetry tracing display |
| `ParamEditorWidget` | `param_editor.py` | Tool parameter editor |
| `PercentageBar` | `percentage_bar.py` | Progress/utilization bars |
| `PodTable` | `pod_table.py` | Kubernetes pod list with status |
| `PodStatusBar` | `pod_table.py` | Pod summary (running/pending/failed counts) |
| `QuickActions` | `quick_actions.py` | Context-sensitive action buttons |
| `RegistryBrowserWidget` | `registry_browser.py` | Server registry browser |
| `RegistryPanelWidget` | `registry_panel.py` | Registry panel |
| `SecretsPanelWidget` | `secrets_panel.py` | Secrets management display |
| `ServerConnectionsPanel` | `server_connections_panel.py` | Server connection panel |
| `ServerGroupsWidget` | `server_groups.py` | Server group management |
| `ServerInfoWidget` | `server_info.py` | Server details (name, version, uptime) |
| `ServerSelectorWidget` | `server_selector.py` | Multi-server dropdown with connect action |
| `SessionsPanelWidget` | `sessions_panel.py` | Active session tracking |
| `SyncStatusWidget` | `sync_status.py` | Config sync status indicator |
| `Toolbar` | `toolbar.py` | Action bar |
| `ToolOpsPanel` | `tool_ops_panel.py` | Tool operations panel |
| `ToolPreviewWidget` | `tool_preview.py` | Tool JSON schema display |
| `TPlot` | `tplot.py` | Plotext-based charts for metrics visualization |
| `VersionBadgeWidget` | `version_badge.py` | Version display badge |
| `VersionDriftWidget` | `version_drift.py` | Version drift detection across backends |
| `WorkflowsPanelWidget` | `workflows_panel.py` | Workflow management panel |

## Custom Events

| Event | File | Trigger |
|-------|------|---------|
| `CapabilitiesReady` | `events.py` | Backend capabilities loaded |
| `ConnectionLost` | `events.py` | Server connection lost |
| `ConnectionRestored` | `events.py` | Server connection restored |
| `ServerSelected` | `widgets/server_selector.py` | User selects a server |
