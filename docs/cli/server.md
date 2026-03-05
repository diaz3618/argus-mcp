# `argus-mcp server`

Start the headless Argus gateway server.

## Usage

```bash
argus-mcp server [--host HOST] [--port PORT] [--log-level LEVEL] [--config PATH]
                 [-d] [--name NAME] [-v | -vv]
```

## Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--host` | string | `127.0.0.1` | Bind address |
| `--port` | integer | `9000` | Listen port |
| `--log-level` | string | `info` | Log level: `debug`, `info`, `warning`, `error`, `critical` |
| `--config` | path | auto-detect | Path to config file (YAML) |
| `-d`, `--detach` | flag | `false` | Run as a detached background process |
| `--name` | string | `default` | Session name for detached mode (max 32 chars, alphanumeric + hyphens) |
| `-v` | flag | — | Show backend connection progress during startup |
| `-vv` | flag | — | Show full subprocess/debug output during startup |

## Config File Resolution

The server resolves the config file using this priority:

1. **`--config` flag** — explicit path (highest priority)
2. **`ARGUS_CONFIG` environment variable** — path from env
3. **Auto-detection** — scans the project directory for:
   - `config.yaml`
   - `config.yml`

The first file found is used. If none exist, the server exits with an error.

## Examples

```bash
# Start with defaults (localhost:9000, auto-detect config)
argus-mcp server

# Custom host and port
argus-mcp server --host 0.0.0.0 --port 8080

# Explicit config file
argus-mcp server --config /etc/argus-mcp/production.yaml

# Debug logging
argus-mcp server --log-level debug

# Verbose startup — show backend connection progress
argus-mcp server -v

# Run as a detached background process
argus-mcp server --detach
argus-mcp server -d --name production

# Using environment variable
export ARGUS_CONFIG=/path/to/config.yaml
argus-mcp server
```

## Server Endpoints

Once running, the server exposes:

| Endpoint | Purpose |
|----------|---------|
| `GET /sse` | SSE transport for MCP clients |
| `POST /messages/` | SSE message submission |
| `GET\|POST\|DELETE /mcp` | Streamable HTTP transport |
| `/manage/v1/*` | Management REST API |

## Management Token

To protect the management API, set a bearer token:

```yaml
# In config.yaml
server:
  management:
    token: "${ARGUS_MGMT_TOKEN}"
```

```bash
export ARGUS_MGMT_TOKEN=my-secret-token
argus-mcp server
```

The `/manage/v1/health` endpoint is always public (no token required).

## Detached Mode

Use `-d` / `--detach` to run the server as a background process with a named
session:

```bash
# Start in background
argus-mcp server -d --name prod

# Check running sessions
argus-mcp status

# Stop the session
argus-mcp stop prod
```

Sessions are tracked in `~/.config/argus-mcp/sessions/`. Each session has a
PID file and log path. Logs are written to `logs/argus-<name>.log`.

## `stop` {#stop}

Stop a named detached server session.

```bash
argus-mcp stop [NAME]
```

- `NAME` — session name (default: `default`)
- Sends `SIGTERM` to the detached process
- Removes the session record on success

## `status` {#status}

List all active detached server sessions.

```bash
argus-mcp status
```

Shows name, PID, port, uptime, and log file for each tracked session.

## Signals

| Signal | Behavior |
|--------|----------|
| `SIGINT` (Ctrl+C) | Graceful shutdown |
| `SIGTERM` | Graceful shutdown |
