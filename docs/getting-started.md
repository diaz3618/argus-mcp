# Getting Started

## Prerequisites

- **Python 3.10+** (3.12 or 3.13 recommended)
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip

## Installation

### From PyPI (recommended)

```bash
# uv tool install — isolated, auto-managed (recommended)
uv tool install argus-mcp

# pipx — same isolation, more established
pipx install argus-mcp

# pip — installs into current environment
pip install argus-mcp
```

Verify:

```bash
argus-mcp --help
```

### From Source

```bash
# Clone and enter the repository
git clone https://github.com/diaz3618/argus-mcp.git
cd argus-mcp

# Install all runtime + dev dependencies
uv sync --group dev

# Or just runtime dependencies
uv sync
```

## Quick Start

### 1. Create a Config File

Argus looks for config files in this order:
`config.yaml` → `config.yml`

Copy and edit the example:

```bash
cp example_config.yaml config.yaml
```

A minimal config with one stdio backend:

```yaml
version: "1"

server:
  host: "127.0.0.1"
  port: 9000

backends:
  my-tool-server:
    type: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-everything"]
```

See [Configuration](configuration.md) for the full reference.

### 2. Start the Server

```bash
argus-mcp server
```

The server starts on `http://127.0.0.1:9000` by default. Override with flags:

```bash
argus-mcp server --host 0.0.0.0 --port 8080 --log-level debug
```

Or point to a specific config file:

```bash
argus-mcp server --config /path/to/my-config.yaml
```

### 3. Connect an MCP Client

Point any MCP-compatible client at one of the Argus transport endpoints:

| Transport | URL |
|-----------|-----|
| SSE | `http://127.0.0.1:9000/sse` |
| Streamable HTTP | `http://127.0.0.1:9000/mcp` |

Example — Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "argus": {
      "url": "http://127.0.0.1:9000/sse"
    }
  }
}
```

### 4. Launch the TUI

In a separate terminal, connect the interactive TUI to the running server:

```bash
argus-mcp tui
```

Or connect to a remote server:

```bash
argus-mcp tui --server http://192.168.1.100:9000
```

### 5. Use the Management API

The management API is available at `/manage/v1/`:

```bash
# Health check (always public)
curl http://127.0.0.1:9000/manage/v1/health

# List backends
curl http://127.0.0.1:9000/manage/v1/backends

# List capabilities
curl http://127.0.0.1:9000/manage/v1/capabilities

# Hot-reload config
curl -X POST http://127.0.0.1:9000/manage/v1/reload
```

If a management token is configured, include the `Authorization` header:

```bash
curl -H "Authorization: Bearer $ARGUS_MGMT_TOKEN" \
     http://127.0.0.1:9000/manage/v1/status
```

## Multi-Server TUI

The TUI supports connecting to multiple Argus instances. Create a
servers config file at `~/.config/argus-mcp/servers.json`:

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
    }
  ],
  "active": "local"
}
```

```bash
argus-mcp tui --servers-config ~/.config/argus-mcp/servers.json
```

## What's Next?

- [Configuration](configuration.md) — Full config reference
- [CLI Reference](cli/) — All command-line options
- [Architecture](architecture/00-overview.md) — How it works
- [Security](security/) — Authentication, RBAC, secrets
- [Management API](api/) — REST endpoint reference
