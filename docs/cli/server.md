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
| `-q`, `--quiet` | flag | `false` | Suppress startup output |

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

## Verbosity Levels

The `-v` / `-vv` / `-q` flags control how much startup output is shown.

| Flag | Level | Behavior |
|------|-------|----------|
| `-q` | -1 | Suppress all startup output |
| *(none)* | 0 | Default — show status summary only |
| `-v` | 1 | Show connection progress and streaming Docker build output |
| `-vv` | 2 | Full subprocess and debug output |

When running parallel builds, `-v` shows the 5 most recent build lines
per active backend; `-vv` shows 10. In sequential mode, `-v` shows 15
lines and `-vv` shows 30.

---

## `build` {#build}

Pre-build container images for all stdio backends before starting the
server. This eliminates first-request build latency.

```bash
argus-mcp build [--config PATH] [--no-parallel] [-v | -vv | -q]
```

### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--config` | path | auto-detect | Path to config file |
| `--no-parallel` | flag | `false` | Build sequentially instead of concurrently |
| `-v` | flag | — | Show build progress |
| `-vv` | flag | — | Full build output |
| `-q`, `--quiet` | flag | `false` | Suppress build output |

### Examples

```bash
# Pre-build all stdio backend images (parallel)
argus-mcp build

# Sequential builds with progress output
argus-mcp build --no-parallel -v

# Build from specific config
argus-mcp build --config /etc/argus-mcp/production.yaml
```

Pre-pulling of base images happens automatically before builds begin.

---

## `clean` {#clean}

Remove containers and images created by Argus MCP. Finds containers
whose image starts with `arguslocal/` and removes them.

```bash
argus-mcp clean [--images] [--network] [--all]
```

### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--images` | flag | `false` | Also remove `arguslocal/` images |
| `--network` | flag | `false` | Also remove the `argus-mcp` Docker network |
| `--all` | flag | `false` | Equivalent to `--images --network` |

### Examples

```bash
# Remove containers only
argus-mcp clean

# Remove containers + images + network
argus-mcp clean --all

# Remove containers and images, keep network
argus-mcp clean --images
```

Containers are removed in batches with a 60-second timeout per batch.
A warning is printed if any containers could not be removed within the
timeout.
