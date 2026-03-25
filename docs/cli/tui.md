# `argus-mcp tui`

Launch the interactive Textual-based terminal UI. The TUI connects to a running
Argus server via its management API and provides real-time monitoring and
control.

## Usage

```bash
argus-mcp tui [--server URL] [--token TOKEN] [--servers-config PATH]
```

## Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--server` | URL | `http://127.0.0.1:9000` | Argus server URL |
| `--token` | string | `None` | Bearer token for management API |
| `--servers-config` | path | `None` | Path to multi-server config (JSON) |

## Authentication

The management token can be provided via:

1. `--token` flag
2. `ARGUS_MGMT_TOKEN` environment variable

If the server has no management token configured, no authentication is needed.

## Examples

```bash
# Connect to local server
argus-mcp tui

# Connect to remote server
argus-mcp tui --server http://192.168.1.100:9000

# With authentication
argus-mcp tui --server http://prod.example.com:9000 --token my-token

# Multi-server mode
argus-mcp tui --servers-config ~/.config/argus-mcp/servers.json
```

## Multi-Server Mode

Create a `servers.json` file to connect to multiple Argus instances:

```json
{
  "servers": [
    {
      "name": "local",
      "url": "http://127.0.0.1:9000"
    },
    {
      "name": "staging",
      "url": "http://staging.example.com:9000",
      "token": "staging-token"
    },
    {
      "name": "production",
      "url": "http://prod.example.com:9000",
      "token": "prod-token"
    }
  ],
  "active": "local"
}
```

Default location: `~/.config/argus-mcp/servers.json`

See the [TUI Guide](../tui/) for screen and keybinding reference.
