# Deployment Hardening

Production checklist and security controls for Argus MCP deployments.

---

## 1. Secrets Strategy

### Management API Token

Set a strong, random bearer token for the management API:

```bash
# Generate a token (≥ 32 bytes of entropy)
python -c "import secrets; print(secrets.token_urlsafe(48))"

export ARGUS_MGMT_TOKEN="<generated-token>"
```

In `config.yaml`:

```yaml
server:
  management:
    enabled: true
    token: "${ARGUS_MGMT_TOKEN}"
```

**Never** commit tokens to version control.  Use environment variables
or the encrypted secret store.

### Encrypted Secret Store

Use the built-in Fernet-encrypted file store for API keys and OAuth
credentials:

```bash
# Generate a master key — store it in a vault or secure env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export ARGUS_SECRET_KEY="<master-key>"

# Store backend credentials
argus-mcp secret set semgrep-api-key
argus-mcp secret set github-token
```

Reference in config:

```yaml
backends:
  my-server:
    headers:
      Authorization: "Bearer secret:semgrep-api-key"
```

Secrets are resolved at startup and automatically redacted from logs.

| Provider | When to use |
|----------|-------------|
| `file` (Fernet) | Default — single-instance deployments |
| `env` | CI/CD, container orchestrators with secret injection |
| `keyring` | Developer workstations with OS keychain |

### Anti-Patterns

- **Do not** store secrets in `config.yaml` as plain text.
- **Do not** pass secrets via CLI flags (visible in `ps` output).
- **Do not** mount secret files with world-readable permissions.

---

## 2. TLS Model

Argus MCP does not terminate TLS directly.  Use a reverse proxy in
front of the server for production deployments.

### Recommended Architecture

```
Client  ──TLS──►  Reverse Proxy  ──HTTP──►  Argus MCP (localhost:9000)
                  (nginx / Caddy / Traefik)
```

### Nginx Example

```nginx
server {
    listen 443 ssl http2;
    server_name mcp.example.com;

    ssl_certificate     /etc/ssl/certs/mcp.example.com.pem;
    ssl_certificate_key /etc/ssl/private/mcp.example.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE / streaming support
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

### Internal Backend Connections

- Backends running on `localhost` or within the same Docker network
  communicate over plain HTTP — this is acceptable when the network
  boundary is trusted.
- Remote backends at external URLs **must** use `https://` URLs.
- Argus verifies TLS certificates for all HTTPS outgoing connections
  (do not set `verify_ssl: false` in production).

---

## 3. SSRF Boundary

Argus connects to backend MCP servers at URLs specified in
`config.yaml`.  Defense against SSRF:

1. **Validate backend URLs** — only configure backends you control.
   Config file access is equivalent to full backend connectivity.
2. **Network segmentation** — run Argus in a network that cannot reach
   internal services (metadata endpoints, cloud IMDSv2, internal APIs)
   unless those services are intentional backends.
3. **Container networking** — use a dedicated Docker network for
   Argus and its backends.  Do not use `--network=host`.
4. **Firewall egress rules** — restrict outbound connections to
   known backend hosts and ports.
5. **Block cloud metadata** — in cloud environments, ensure the
   instance metadata service (169.254.169.254) is unreachable from
   the Argus container.

### Docker Network Isolation

```bash
# Create a dedicated network
docker network create argus-net

# Run Argus on the isolated network
docker run --network=argus-net -p 9000:9000 argus-mcp
```

---

## 4. Non-Root Container Checklist

The official Docker image runs as a non-root `argus` user (UID/GID
assigned by `groupadd -r` / `useradd -r`).

### Verify at Runtime

```bash
docker run --rm argus-mcp whoami
# Output: argus

docker run --rm argus-mcp id
# Output: uid=999(argus) gid=999(argus) groups=999(argus)
```

### Hardening Flags

```bash
docker run \
  --read-only \
  --tmpfs /tmp \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -v ./config.yaml:/app/config.yaml:ro \
  -v argus-logs:/app/logs \
  -p 9000:9000 \
  argus-mcp
```

| Flag | Purpose |
|------|---------|
| `--read-only` | Immutable root filesystem |
| `--tmpfs /tmp` | Writable tmp for transient data |
| `--cap-drop ALL` | Drop all Linux capabilities |
| `--security-opt no-new-privileges` | Prevent privilege escalation |
| `:ro` on config mount | Read-only config file |
| Named volume for logs | Persistent, writable audit trail |

### Container Isolation for Stdio Backends

Argus automatically runs stdio backends (`uvx`, `npx` commands) inside
isolated containers with:

- Non-root execution
- Read-only root filesystem (where supported)
- `--cap-drop ALL`
- Memory and CPU resource limits
- No network access unless explicitly configured

Control via feature flags:

```yaml
feature_flags:
  container_isolation: true   # Enable container wrapping (default: on)
  build_on_startup: true      # Pre-build images at startup (default: on)
```

---

## 5. Deployment Validation Checklist

Run these checks before any production deployment.

### Minimum Environment

| Requirement | Check |
|-------------|-------|
| `ARGUS_MGMT_TOKEN` set | `test -n "$ARGUS_MGMT_TOKEN"` |
| `ARGUS_SECRET_KEY` set (if using file secrets) | `test -n "$ARGUS_SECRET_KEY"` |
| Config file exists | `test -f config.yaml` |
| Config file not world-readable | `stat -c %a config.yaml` returns `600` or `640` |
| Non-root execution | `docker run --rm <image> whoami` returns non-root |
| Health endpoint responds | `curl -sf http://localhost:9000/manage/v1/health` |

### Feature Flags

| Flag | Recommended | Notes |
|------|-------------|-------|
| `optimizer` | `false` (default) | High-risk — enable only after testing |
| `hot_reload` | `true` | Safe for production |
| `outgoing_auth` | `true` | Required for OAuth backends |
| `session_management` | `true` | Required for multi-client setups |
| `container_isolation` | `true` | Critical for untrusted stdio backends |
| `build_on_startup` | `true` | Pre-builds avoid first-request latency |

### Authentication

| Mode | When to use |
|------|-------------|
| `anonymous` | Development only |
| `local` | Single-user or air-gapped deployments |
| `jwt` | API-to-API with shared signing key |
| `oidc` | Multi-user with identity provider (recommended) |

### Failure Modes

| Failure | Behavior | Mitigation |
|---------|----------|------------|
| Backend unreachable | Circuit breaker opens after threshold | Auto-retry with backoff; check `/manage/v1/status` |
| Config parse error | Server refuses to start | Validate with `argus-mcp config validate` before deploy |
| Secret key missing | Secret resolution fails, server exits | Ensure `ARGUS_SECRET_KEY` is injected |
| Management token missing | Management API is unauthenticated | Always set `ARGUS_MGMT_TOKEN` in production |
| Audit log write fails | Logged to stderr as fallback | Mount writable volume at `/app/logs` |

### Pre-Deploy Script

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Required environment
: "${ARGUS_MGMT_TOKEN:?ARGUS_MGMT_TOKEN must be set}"

# 2. Config exists and parses
argus-mcp config validate --config config.yaml

# 3. Image runs as non-root
user=$(docker run --rm argus-mcp whoami)
if [ "$user" = "root" ]; then
  echo "ERROR: Container runs as root" >&2
  exit 1
fi

echo "Deployment checks passed."
```
