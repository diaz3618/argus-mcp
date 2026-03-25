# Getting Started

## Prerequisites

- **Python 3.10+** (3.12 or 3.13 recommended)
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **Go 1.25+** — only needed if you want to build the `argusd` daemon

## Package Overview

Argus ships as three packages that can be installed independently:

| Package | Language | Description |
|---------|----------|-------------|
| **argus-mcp** | Python | The MCP gateway server — aggregates backends, exposes SSE / Streamable HTTP transports, management API, and a built-in TUI. |
| **argus-cli** | Python | Interactive client CLI and REPL for managing a running Argus server. Ships the `argus` and `argus-tui` commands. |
| **argusd** | Go | Lightweight sidecar daemon for Docker and Kubernetes management over a Unix Domain Socket. |

Only `argus-mcp` is required. Install the other packages when you need them.

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

### argus-cli (client)

The client CLI lives in `packages/argus_cli/` and can be installed from source:

```bash
cd packages/argus_cli

# With uv
uv pip install -e .

# With TUI support
uv pip install -e ".[tui]"

# Or plain pip
pip install -e .
```

Verify:

```bash
argus --help
```

### argusd (Go daemon)

The sidecar daemon lives in `packages/argusd/` and is built with Go:

```bash
cd packages/argusd
make build
```

The resulting `argusd` binary listens on a Unix Domain Socket
(`/var/run/argusd.sock` by default).

See [Architecture — argusd](architecture/07-argusd.md) for full details.

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

> **Container isolation**: When Docker or Podman is available on the host,
> Argus automatically builds and runs each stdio backend inside a hardened
> container. No extra config is needed — it happens transparently at startup.
> See [Configuration — Container Isolation](configuration.md#automatic-container-isolation)
> for details.

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

Use `-v` to see backend connection progress during startup, or `-vv` for
full subprocess output:

```bash
argus-mcp server -v
```

#### Pre-building Container Images

When container isolation is enabled (the default), each stdio backend's
container image is built on first startup. To avoid this latency, pre-build
all images:

```bash
argus-mcp build
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

### 6. Use the argus Client CLI

With the server running, use the `argus` client for one-shot commands or an
interactive REPL session:

```bash
# One-shot commands
argus backends list
argus tools list --output json
argus health status

# Connect to a specific server
argus -s http://192.168.1.100:9000 backends list
```

Start the interactive REPL (tab completion, history, status toolbar):

```bash
argus
```

Or launch the enhanced TUI directly:

```bash
argus-tui
```

See [CLI Reference](cli/README.md) for all 20 command groups and
[REPL Guide](cli/repl.md) for REPL details.

### 7. Run argusd (optional)

If you need Docker container or Kubernetes pod management from the CLI,
start the `argusd` daemon:

```bash
cd packages/argusd
make run
```

The daemon exposes a local HTTP API over a Unix Domain Socket. The `argus`
client commands `argus containers` and `argus pods` communicate with it
automatically when the socket is available.

See [Architecture — argusd](architecture/07-argusd.md) for configuration
and deployment options.

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

## Cleanup

Remove containers and images created by Argus:

```bash
# Remove containers only
argus-mcp clean

# Remove everything (containers + images + network)
argus-mcp clean --all
```

## What's Next?

- [Configuration](configuration.md) — Full config reference
- [CLI Reference](cli/) — All command-line options
- [Architecture](architecture/00-overview.md) — How it works
- [Security](security/) — Authentication, RBAC, secrets
- [Management API](api/) — REST endpoint reference
