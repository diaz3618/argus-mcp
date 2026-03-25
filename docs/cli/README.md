# CLI Reference

Argus has two CLI entry points — the **server package** (`argus-mcp`) and the
**client package** (`argus`).

## argus-mcp (server)

The `argus-mcp` binary manages the server-side gateway process.

| Command | Description |
|---------|-------------|
| [`argus-mcp server`](server.md) | Run the headless gateway server |
| [`argus-mcp stop`](server.md#stop) | Stop a detached background server |
| [`argus-mcp status`](server.md#status) | List all running detached sessions |
| [`argus-mcp tui`](tui.md) | Launch the interactive terminal UI |
| [`argus-mcp secret`](secret.md) | Manage encrypted secrets |
| [`argus-mcp build`](server.md#build) | Pre-build container images for stdio backends |
| [`argus-mcp clean`](server.md#clean) | Remove containers and images created by Argus |

### Usage

```
argus-mcp [-h] {server,stop,status,tui,secret,build,clean} ...
```

### Entry Point

Installed as the `argus-mcp` console script (defined in `pyproject.toml`).
Also invocable as a Python module:

```bash
python -m argus_mcp server
```

---

## argus (client)

The `argus` binary is an interactive client for managing a running Argus server.
It ships in the separate **argus-cli** package (`packages/argus_cli/`).

### Dual-mode Operation

- **One-shot mode**: `argus <command> [subcommand] [options]` — run a single
  command and exit.
- **REPL mode**: `argus` (no arguments) — start an interactive session with
  tab completion, history, and a status toolbar.

See [REPL Guide](repl.md) for REPL details.

### Command Groups

| Group | Description |
|-------|-------------|
| `argus audit` | Query and export audit log entries |
| `argus auth` | Authentication management (status, configure, test) |
| `argus backends` | Backend lifecycle (list, inspect, reconnect) |
| `argus batch` | Bulk operations across backends |
| `argus config` | View and reload configuration |
| `argus config-server` | Server-side config management |
| `argus containers` | Docker container management (via argusd) |
| `argus events` | Event stream queries and live streaming |
| `argus health` | Health status and active sessions |
| `argus operations` | Optimizer and telemetry controls |
| `argus pods` | Kubernetes pod management (via argusd) |
| `argus prompts` | MCP prompts (list, get) |
| `argus registry` | Server registry (search, install) |
| `argus resources` | MCP resources (list, read) |
| `argus secrets` | Secrets management (list, set, get, delete) |
| `argus server` | Server lifecycle (start, stop, status) |
| `argus skills` | Skill pack management |
| `argus tools` | MCP tools (list, inspect, call) |
| `argus workflows` | Workflow management (list, run, history) |

### Global Options

| Option | Env Var | Description |
|--------|---------|-------------|
| `--server`, `-s` | `ARGUS_SERVER_URL` | Argus server URL |
| `--token`, `-t` | `ARGUS_MGMT_TOKEN` | Management API token |
| `--output`, `-o` | — | Output format: rich, json, table, text |
| `--theme` | — | Color theme name |
| `--no-color` | — | Disable colored output |
| `--version` | — | Show version and exit |

### Entry Points

Installed as two console scripts (defined in `packages/argus_cli/pyproject.toml`):

| Script | Description |
|--------|-------------|
| `argus` | CLI and REPL (Typer) |
| `argus-tui` | Launch the TUI directly |

### Usage Examples

```bash
# One-shot commands
argus backends list
argus tools list --output json
argus tools call my-tool --params '{"key": "value"}'
argus containers list
argus health status

# Connect to a specific server
argus -s http://192.168.1.100:9000 backends list

# Start the REPL
argus

# Launch the TUI
argus-tui
```

## Global Help

```bash
argus-mcp --help
argus --help
argus backends --help
```
