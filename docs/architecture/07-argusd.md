# argusd — Sidecar Daemon

`argusd` is a lightweight Go daemon that exposes Docker and Kubernetes
operations for Argus-managed resources over an HTTP API on a Unix Domain Socket.

The `argus` CLI and TUI connect to argusd via the `DaemonClient` to provide
container and pod management features.

## Architecture

```
┌────────────┐         UDS          ┌──────────┐
│ argus CLI  │─────────────────────►│ argusd   │
│ argus TUI  │  /v1/containers/*    │          │
│            │  /v1/pods/*          │ Docker   │──► Docker Engine API
│            │  /v1/events          │ K8s      │──► Kubernetes API
└────────────┘                      └──────────┘
```

## Running

```bash
# Default socket path: $XDG_RUNTIME_DIR/argusd.sock (or /tmp/argusd.sock)
argusd

# Custom socket path
argusd -socket /var/run/argusd.sock
```

argusd requires Docker to be available. Kubernetes support is optional — if
no kubeconfig or in-cluster config is detected, K8s endpoints are not
registered.

> **Note**: Building argusd (`make build`) only compiles the binary.
> You must also start it — either manually or via auto-start (see below).

## CLI Configuration

The `argus` CLI config file (`~/.config/argus-mcp/config.yaml`) supports
an `argusd` section for daemon-related settings:

```yaml
argusd:
  # Automatically start argusd when the CLI/TUI needs it and the
  # socket is not found. Default: false
  auto_start: false

  # Explicit path to the argusd binary. If omitted, the CLI searches:
  #   1. $PATH
  #   2. packages/argusd/argusd (repo build directory)
  # binary: "/usr/local/bin/argusd"

  # Custom socket path. If omitted, uses the daemon default:
  #   $XDG_RUNTIME_DIR/argusd.sock  or  /tmp/argusd.sock
  # socket: "/run/user/1000/argusd.sock"
```

Environment variables override config file values:

| Variable | Description |
|----------|-------------|
| `ARGUSD_AUTO_START` | Set to `true`, `1`, or `yes` to enable auto-start |
| `ARGUSD_BINARY` | Path to the argusd binary |
| `ARGUSD_SOCKET` | Custom socket path |

### Auto-start behavior

When `auto_start: true` is set and a CLI/TUI command needs argusd:

1. The `DaemonClient` checks if the socket file exists.
2. If missing, it locates the argusd binary (explicit path → `$PATH` →
   repo build dir).
3. Spawns argusd as a detached background process with the configured
   socket path.
4. Waits up to 3 seconds for the socket to appear.
5. If the socket appears, the client connects normally. If not, an error
   is displayed.

The auto-started daemon runs independently — it persists after the CLI
exits. Stop it with `pkill argusd` or by sending SIGTERM.

## API Reference

All endpoints are served over the Unix Domain Socket. The `DaemonClient` in
`argus_cli/daemon_client.py` handles the UDS transport via httpx.

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/health` | Daemon health check |

### Docker Containers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/containers` | List Argus-labeled containers |
| GET | `/v1/containers/{id}` | Inspect a container |
| POST | `/v1/containers/{id}/start` | Start a container |
| POST | `/v1/containers/{id}/stop` | Stop a container |
| POST | `/v1/containers/{id}/restart` | Restart a container |
| POST | `/v1/containers/{id}/remove` | Remove a container |
| GET | `/v1/containers/{id}/logs` | Stream container logs (SSE) |
| GET | `/v1/containers/{id}/stats` | Stream container stats (SSE) |

### Docker Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/events` | Stream Docker events (SSE) |

### Kubernetes Pods

These endpoints are only available when Kubernetes is reachable.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/pods` | List Argus-managed pods |
| GET | `/v1/pods/{ns}/{name}` | Describe a pod |
| DELETE | `/v1/pods/{ns}/{name}` | Delete a pod |
| GET | `/v1/pods/{ns}/{name}/logs` | Stream pod logs (SSE) |
| GET | `/v1/pods/{ns}/{name}/events` | Pod events |

### Kubernetes Deployments

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/deployments/{ns}/{name}/restart` | Rollout restart |

## Resource Labeling

argusd uses Docker labels and Kubernetes labels to identify Argus-managed
resources. Only resources with the appropriate Argus labels are returned by
list endpoints. The labeling contract is defined in
`packages/argusd/internal/labels/labels.go`.

## Package Structure

```
packages/argusd/
├── cmd/argusd/main.go           # Entry point — flag parsing, server setup
├── go.mod, go.sum               # Go module definition
├── Makefile                     # Build targets
└── internal/
    ├── docker/client.go         # Docker Engine API client
    ├── k8s/client.go            # Kubernetes API client
    ├── labels/labels.go         # Label constants and filters
    └── server/
        ├── router.go            # HTTP route registration
        ├── handlers.go          # Request handler implementations
        └── sse.go               # Server-Sent Events streaming helpers
```

## Security

- The socket is created with `0600` permissions (owner-only access).
- argusd only exposes Argus-labeled resources, not all Docker containers.
- Stale socket files are removed on startup.
- Graceful shutdown on SIGINT/SIGTERM with a 5-second timeout.
