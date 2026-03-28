# Argus CLI

Interactive CLI for [Argus MCP](https://github.com/diaz3618/argus-mcp) — dual-mode REPL + one-shot commands.

## Installation

```bash
pip install argus-cli        # REPL + one-shot CLI
pip install argus-cli[tui]   # adds TUI frontend
```

## Usage

```bash
argus              # launch interactive REPL
argus status       # one-shot command
argus tui          # launch TUI (requires tui extra)
```

## Entry Points

| Command | Description |
|---------|-------------|
| `argus` | Main CLI / interactive REPL |
| `argus-cli` | Alias for `argus` |
| `argus-tui` | Launch the TUI frontend (requires `tui` extra) |

## Command Groups

| Group | Description |
|-------|-------------|
| `status` | Server status overview |
| `health` | Health and readiness probes |
| `backends` | List and inspect backend connections |
| `tools` | Browse and call aggregated MCP tools |
| `resources` | Browse and read aggregated MCP resources |
| `prompts` | Browse aggregated MCP prompts |
| `events` | View recent server events |
| `sessions` | List active MCP client sessions |
| `config` | View server configuration |
| `config-server` | Retrieve running server config |
| `operations` | Reload, reconnect, and shutdown |
| `batch` | Fetch combined status/backends/capabilities/events |
| `auth` | Authentication status and re-auth |
| `audit` | View audit log entries |
| `registry` | Search external MCP server registries |
| `skills` | List, enable, and disable skills |
| `workflows` | List and manage workflows |
| `secrets` | Manage encrypted secrets |
| `containers` | Docker container management (via argusd) |
| `pods` | Kubernetes pod management (via argusd) |
| `server` | Start/stop argus-mcp server |

## Documentation

See the full [CLI Reference](../../docs/cli/) and [REPL Guide](../../docs/cli/repl.md).
