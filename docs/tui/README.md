# TUI Guide

Argus MCP includes an interactive terminal UI built with
[Textual](https://textual.textualize.io/). The TUI connects to a running
Argus server via the management API and provides real-time monitoring,
capability browsing, and server control.

## Launching

```bash
# Connect to local server (default: http://127.0.0.1:9000)
argus-mcp tui

# Connect to remote server
argus-mcp tui --server http://192.168.1.100:9000

# With authentication
argus-mcp tui --token my-management-token

# Multi-server mode
argus-mcp tui --servers-config ~/.config/argus-mcp/servers.json
```

See [`argus-mcp tui`](../cli/tui.md) for all CLI options.

## Screens

The TUI has ten modes, accessible via keybindings or the command palette.

### Dashboard (key: `1` or `d`)

The default screen showing an overview of the Argus instance:

- **Server Info** — Name, version, uptime, transport URLs
- **Backend Status** — Connection state and health for each backend,
  with status dots (● healthy, ◑ degraded, ✕ failed) and phase icons
  from the shared design module
- **Event Log** — Real-time event stream with severity indicators
- **Capability Summary** — Quick counts of tools, resources, and prompts

### Tools (key: `2`)

Full-screen capability explorer:

- Browse all aggregated tools, resources, and prompts
- Filter by capability type (key: `t` tools, `r` resources, `p` prompts)
- Search by name
- View detailed capability information including schemas

### Registry (key: `3`)

Server browser and discovery:

- Browse available MCP servers from the registry
- View server details and metadata
- Install panel for adding new backends

### Settings (key: `4` or `s`)

Configuration and preferences:

- View current config (read from server)
- Theme selection
- TUI preferences

### Skills (key: `5`)

Skill pack management:

- Browse installed skills with enable/disable status
- Enable, disable, and apply skills
- View skill manifests and workflow details

### Editor (key: `6`)

Tool parameter editing and testing:

- Edit tool parameters with type-aware input fields
- JSON schema visualization
- Test invocation (dry-run)

### Audit (key: `7`)

Audit log viewer:

- Browse structured audit events
- Filter by method, backend, and status
- View event details with timing information

### Health (key: `8` or `h`)

Backend health monitoring:

- Per-backend health status and history
- Health check configuration
- Version drift detection

### Security (key: `9`)

Security overview:

- Authentication status and configuration
- Active sessions and middleware chain
- Secrets and network isolation status

### Operations (key: `0` or `o`)

Operational controls:

- Backend management (reconnect, restart)
- Server groups and sync status
- Workflow management

## Keybindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `1` or `d` | Switch to Dashboard |
| `2` | Switch to Tools |
| `3` | Switch to Registry |
| `4` or `s` | Switch to Settings |
| `5` | Switch to Skills |
| `6` | Switch to Editor |
| `7` | Switch to Audit |
| `8` or `h` | Switch to Health |
| `9` | Switch to Security |
| `0` or `o` | Switch to Operations |
| `t` | Show Tools tab |
| `r` | Show Resources tab |
| `p` | Show Prompts tab |
| `n` | Cycle theme |
| `T` (Shift) | Open theme picker |
| `Ctrl+P` | Command palette |

## Command Palette

Press `Ctrl+P` to open the command palette with quick access to:

- All TUI modes (Dashboard, Tools, Registry, Settings, Skills, etc.)
- REPL-style navigation verbs (e.g. `backends list`, `health`, `audit`)
- Theme switching with live preview
- Server details and connection info
- Tools/Resources/Prompts tab switching

## Polling

The TUI polls the management API every 2 seconds to refresh:

- Health status
- Backend states
- Capabilities
- Events

### Connection Handling

- **Connection lost**: TUI shows a connection-lost indicator and continues
  polling. It will reconnect automatically when the server becomes available.
- **Connection restored**: TUI resumes normal operation and refreshes all data.

## Multi-Server Mode

With a `servers.json` config, the TUI shows a server selector widget allowing
you to switch between multiple Argus instances:

```json
{
  "servers": [
    { "name": "local", "url": "http://127.0.0.1:9000" },
    { "name": "staging", "url": "http://staging:9000", "token": "tok" }
  ],
  "active": "local"
}
```

The server selector appears at the top of the dashboard. Selecting a different
server reconnects the TUI to that instance.

## Theming

The TUI supports Textual's built-in themes. Cycle through themes with `n` or
open the theme picker with `T` (Shift+T) for a visual preview.

When a Textual theme is selected, the matching YAML palette is activated
automatically so Rich output (status dots, tables, etc.) stays visually
consistent with the TUI chrome. Custom YAML palettes can be placed in
`~/.config/argus-mcp/themes/`.

## Design System

Both the TUI and REPL share a unified visual language defined in
`argus_cli/design.py`:

| Convention | Examples |
|------------|----------|
| Status dots | ● healthy, ● connected, ◑ degraded, ○ disconnected, ✕ error |
| Phase icons | ◌ pending, ⟳ initializing, ● ready, ◑ degraded, ✕ failed |
| Transport badges | `stdio`, `SSE`, `StreamableHTTP` |

## Additional Screens

| Screen | Purpose |
|--------|---------|
| Elicitation | Handle elicitation requests from backends |
| Theme Picker | Visual theme selection with previews |

See [Screens Reference](screens.md) for detailed screen documentation.
