# Docker Usage

Argus MCP publishes multi-architecture images (`linux/amd64`, `linux/arm64`) to both Docker Hub and GHCR:

| Registry | Image |
|----------|-------|
| Docker Hub | `diaz3618/argus-mcp` |
| GHCR | `ghcr.io/diaz3618/argus-mcp` |

## Quick Start — Server

```bash
docker run -d \
  --name argus \
  -p 9000:9000 \
  -v ./config.yaml:/app/config.yaml \
  diaz3618/argus-mcp:latest
```

The server listens on `0.0.0.0:9000` by default and exposes:

- **SSE** — `http://localhost:9000/sse`
- **Streamable HTTP** — `http://localhost:9000/mcp`
- **Management API** — `http://localhost:9000/manage/v1/`

### Custom Port

```bash
docker run -d \
  --name argus \
  -p 8080:8080 \
  -v ./config.yaml:/app/config.yaml \
  diaz3618/argus-mcp:latest \
  server --host 0.0.0.0 --port 8080
```

### Environment Variables

Pass environment variables referenced in your config with `-e`:

```bash
docker run -d \
  --name argus \
  -p 9000:9000 \
  -v ./config.yaml:/app/config.yaml \
  -e ARGUS_MGMT_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -e MY_API_KEY=sk-xxx \
  diaz3618/argus-mcp:latest
```

Or use an env file:

```bash
docker run -d \
  --name argus \
  -p 9000:9000 \
  -v ./config.yaml:/app/config.yaml \
  --env-file .env \
  diaz3618/argus-mcp:latest
```

### Logs

Mount a volume to persist logs outside the container:

```bash
docker run -d \
  --name argus \
  -p 9000:9000 \
  -v ./config.yaml:/app/config.yaml \
  -v ./logs:/app/logs \
  diaz3618/argus-mcp:latest
```

### Health Check

The image includes a built-in health check against `/manage/v1/health`. Check status with:

```bash
docker inspect --format='{{.State.Health.Status}}' argus
```

## TUI (Client)

The TUI is a terminal application that connects to a running Argus server over HTTP. It requires a TTY, so use `-it`:

```bash
docker run --rm -it \
  diaz3618/argus-mcp:latest \
  tui --server http://host.docker.internal:9000
```

> **Note:** Use `host.docker.internal` to reach a server running on the Docker host. On Linux without Docker Desktop, you may need `--add-host=host.docker.internal:host-gateway` or use the host's LAN IP.

### Connecting to a Remote Server

```bash
docker run --rm -it \
  diaz3618/argus-mcp:latest \
  tui --server https://argus.example.com:9000 --token YOUR_TOKEN
```

## Docker Compose

`docker-compose.yml` for running the server:

```yaml
services:
  argus:
    image: diaz3618/argus-mcp:latest
    ports:
      - "9000:9000"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./logs:/app/logs
    environment:
      ARGUS_MGMT_TOKEN: "${ARGUS_MGMT_TOKEN}"
    restart: unless-stopped
```

## Building Locally

```bash
docker build -t argus-mcp .
docker run -p 9000:9000 -v ./config.yaml:/app/config.yaml argus-mcp
```

## Image Details

- **Base:** `python:3.13-slim`
- **Node.js:** LTS (22.x) included for `npx`-based stdio backends
- **User:** Runs as non-root user
- **Entrypoint:** `argus-mcp` — pass any subcommand (`server`, `tui`, `secret`) as arguments
- **Default command:** `server --host 0.0.0.0 --port 9000`

## Backend Container Isolation

Argus automatically builds and runs each **stdio backend** inside its own
hardened container. This provides process-level isolation, resource limits,
and a read-only filesystem for every backend — with no manual Docker
configuration required.

### How It Works

When the server starts (or when `argus-mcp build` is run), Argus:

1. **Detects** a container runtime (Docker or Podman) on the host
2. **Classifies** each backend's command (`uvx`, `npx`, `go`, etc.)
3. **Builds** a purpose-built Docker image from a Jinja2 template
4. **Pre-creates** a container with security hardening flags
5. **Attaches** via `docker start -ai` for stdio communication

### Security Defaults

Every backend container runs with:

- `--read-only` filesystem + tmpfs for `/tmp` and `/home/nonroot`
- `--cap-drop ALL` — no Linux capabilities
- `--security-opt no-new-privileges`
- `--memory 512m --cpus 1` (configurable per backend)
- Non-root user (UID 65532, the distroless/Chainguard standard)

### Pre-Building Images

To avoid cold-start delays, pre-build all backend images:

```bash
argus-mcp build --config config.yaml
```

This builds images and pre-creates containers for all configured stdio
backends. The server then starts instantly by attaching to pre-created
containers.

### Relationship to Argus Server Image

The Argus **server image** (`diaz3618/argus-mcp`) runs the gateway itself.
Backend container isolation is a separate layer: the gateway process builds
and manages individual backend containers on the Docker host. When running
the Argus server inside Docker, the server container needs access to the
Docker socket (`-v /var/run/docker.sock:/var/run/docker.sock`) to manage
backend containers.

### Disabling Container Isolation

Set the environment variable or config flag:

```bash
ARGUS_CONTAINER_ISOLATION=false
```

```yaml
feature_flags:
  container_isolation: false
```

Individual backends can also opt out:

```yaml
backends:
  my-backend:
    container_isolation: false
```

## Pinning a Version

Use a specific tag instead of `latest`:

```bash
docker pull diaz3618/argus-mcp:0.8.1
```

Tags follow the project version (semver) and are published on each release.
Both `diaz3618/argus-mcp` (Docker Hub) and `ghcr.io/diaz3618/argus-mcp` (GHCR)
carry the same tags. All images are multi-arch (`linux/amd64`, `linux/arm64`).
