# Argus MCP Security Guide

This guide covers security configuration, deployment hardening, and threat
mitigations for Argus MCP. It consolidates findings from the security
assessment documented in `internal/reports/security/README.md`.

## Authentication and Authorization

### Management API Tokens

The management API requires a bearer token for all mutating operations.

**Token requirements:**

- Minimum 32 characters, generated with a CSPRNG.
- Store using `argus-mcp secret set mgmt_token` (encrypted at rest) or the
  `ARGUS_MGMT_TOKEN` environment variable.
- On Kubernetes, use a Secret — never a ConfigMap
  (see `charts/argus-mcp/README.md` for the `existingSecret` pattern).

**Rotation:** Update the secret store or environment variable and restart the
gateway process. Active sessions are not invalidated; configure rate limiting
to mitigate brute-force attempts during rotation windows.

### RBAC Default Behavior

When RBAC is enabled (`security.rbac.enabled: true`), the default effect is
**deny** (`default_effect: deny`). Clients without an explicit allow rule
receive a 403 response. This was confirmed as the intended default in v0.8.2
(SEC-16 / VULN-006).

Configure roles and bindings in `config.yaml`:

```yaml
security:
  rbac:
    enabled: true
    default_effect: deny
    roles:
      reader:
        allow: ["tools/list", "resources/list"]
      admin:
        allow: ["*"]
```

## Transport Security (TLS)

> **TLS is required for all production deployments.** (SEC-08 / VULN-025)

Without TLS, bearer tokens and tool call payloads traverse the network in
cleartext. Deployment options:

| Method | Complexity | Notes |
|---|---|---|
| Reverse proxy (nginx, Caddy) | Low | Terminate TLS at the proxy |
| Kubernetes Ingress + cert-manager | Low | Recommended for K8s |
| Service mesh (Istio, Linkerd) | Medium | Mutual TLS between services |
| Native uvicorn TLS | Medium | `--ssl-keyfile` / `--ssl-certfile` |

When TLS is detected the `SecurityHeadersMiddleware` automatically injects
`Strict-Transport-Security` (HSTS) with a one-year max-age (SEC-14 fix).

## Filesystem Backend Safety

> **Warning:** Filesystem backends execute with the gateway process
> privileges. (SEC-04 / VULN-016)

- Never point `allowed_directories` at sensitive system paths (`/etc`,
  `/root`, `/var/run`, `/proc`).
- Use dedicated data directories with restricted POSIX permissions
  (e.g., `0750` owned by the service user).
- In Docker, mount only specific directories and prefer read-only bind mounts
  (`ro`) where the backend does not need write access.

```yaml
backends:
  filesystem:
    type: stdio
    command: ["npx", "@anthropic/filesystem-mcp"]
    args:
      allowed_directories:
        - /data/projects  # scoped, non-sensitive
```

## Supabase Backend SQL Scoping

> **Warning:** The Supabase backend executes SQL within the configured project
> scope. (SEC-09 / VULN-022)

- Use the **anon key** (not the service-role key) so that Row-Level Security
  (RLS) policies are enforced.
- Enable RLS on every table accessed through Argus MCP.
- Scope the Supabase project to the minimum required tables and functions.

```yaml
backends:
  supabase:
    type: sse
    url: "https://<project>.supabase.co/mcp/v1"
    headers:
      apikey: "${SUPABASE_ANON_KEY}"
```

## Health Endpoint Information Disclosure

The `/health` endpoint returns the server version string (SEC-18 / VULN-001).
This is an **accepted risk** for an open-source project — the version is
publicly available via PyPI and GitHub releases. Monitoring systems rely on
the version field for alerting.

For sensitive deployments, place a reverse proxy in front of the gateway and
strip the version from the JSON response body.

## Server Version in HTTP Headers

The `Server` HTTP response header includes the Argus MCP version
(SEC-22 / VULN-004). This is **accepted** for the same reason as the health
endpoint disclosure above.

To suppress the header, configure your reverse proxy to remove or override
the `Server` header (e.g., `proxy_hide_header Server;` in nginx).

## Resolved Findings Reference

| SEC ID | VULN ID | Title | Status | Version |
|---|---|---|---|---|
| SEC-16 | VULN-006 | RBAC default permits all | Fixed | v0.8.2 |
| SEC-18 | VULN-001 | Health endpoint version disclosure | N/A — accepted | v0.8.2 |
| SEC-22 | VULN-004 | Server header version disclosure | N/A — accepted | v0.8.2 |
| SEC-23 | VULN-012 | ServiceAccount over-privileged | Fixed | v0.8.2 |

## Deployment Checklist

Use this checklist before promoting a deployment to production:

- [ ] TLS enabled (reverse proxy, Ingress, or native)
- [ ] Management token ≥ 32 characters, stored in secret store or K8s Secret
- [ ] NetworkPolicy applied restricting egress to backend CIDRs only (K8s)
- [ ] Filesystem backends use scoped, non-sensitive directories
- [ ] Supabase backends use the anon key with RLS enabled
- [ ] Rate limiting enabled (`security.rate_limit.enabled: true`, default)
- [ ] Security headers enabled (`security.headers.enabled: true`, default)
- [ ] Payload size limits configured (`security.payload_limits.enabled: true`)
- [ ] RBAC enabled with `default_effect: deny` for multi-tenant deployments
- [ ] Origin validation set to strict mode for browser-facing deployments
