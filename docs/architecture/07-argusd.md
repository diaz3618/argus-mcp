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
