# TUI Screens Reference

## Screen Architecture

All screens extend a common `BaseScreen` and implement `compose_content()` for
layout. The TUI uses Textual's mode system — each screen is registered as a
mode in `ArgusApp`.

```
ArgusApp
├── DashboardScreen   (mode: "dashboard",   key: 1/d)
├── ToolsScreen       (mode: "tools",        key: 2)
├── RegistryScreen    (mode: "registry",     key: 3)
├── SettingsScreen    (mode: "settings",     key: 4/s)
├── SkillsScreen      (mode: "skills",       key: 5)
├── ToolEditorScreen  (mode: "editor",       key: 6)
├── AuditLogScreen    (mode: "audit",        key: 7)
├── HealthScreen      (mode: "health",       key: 8/h)
├── SecurityScreen    (mode: "security",     key: 9)
└── OperationsScreen  (mode: "operations",   key: 0/o)
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

Structured audit event browser:

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

## ThemeScreen

**File:** `tui/screens/theme_picker.py`
**Key:** `T` (Shift+T)

Visual theme selection:

- Preview of available Textual themes
- Live preview before applying
- Persistent theme preference

## Widget Reference

| Widget | File | Description |
|--------|------|-------------|
| `BackendStatusWidget` | `backend_status.py` | Backend lifecycle display (uses `design.py` status dots) |
| `CapabilitySection` | `capability_tables.py` | Tabbed tables for tools/resources/prompts |
| `ElicitationFormWidget` | `elicitation_form.py` | Dynamic elicitation form |
| `EventLogWidget` | `event_log.py` | Scrollable event timeline |
| `FilterToggleWidget` | `filter_toggle.py` | Capability filter controls |
| `HealthPanelWidget` | `health_panel.py` | Per-backend health status and history |
| `InstallPanelWidget` | `install_panel.py` | Backend installation form |
| `MiddlewarePanelWidget` | `middleware_panel.py` | Middleware chain visualization |
| `NetworkPanelWidget` | `network_panel.py` | Network isolation status |
| `OptimizerPanelWidget` | `optimizer_panel.py` | Optimizer controls and metrics |
| `OtelPanelWidget` | `otel_panel.py` | OpenTelemetry tracing display |
| `ParamEditorWidget` | `param_editor.py` | Tool parameter editor |
| `RegistryBrowserWidget` | `registry_browser.py` | Server registry browser |
| `SecretsPanelWidget` | `secrets_panel.py` | Secrets management display |
| `ServerGroupsWidget` | `server_groups.py` | Server group management |
| `ServerInfoWidget` | `server_info.py` | Server details (name, version, uptime) |
| `ServerSelectorWidget` | `server_selector.py` | Multi-server dropdown with connect action |
| `SessionsPanelWidget` | `sessions_panel.py` | Active session tracking |
| `SyncStatusWidget` | `sync_status.py` | Config sync status indicator (uses `design.py` status dots) |
| `Toolbar` | `toolbar.py` | Action bar |
| `ToolPreviewWidget` | `tool_preview.py` | Tool JSON schema display |
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
