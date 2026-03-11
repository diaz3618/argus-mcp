# Audit & Observability

Argus MCP provides structured audit logging, OpenTelemetry integration,
and backend health monitoring for production observability.

## Audit Logging

### Overview

Every MCP operation (tool call, resource read, prompt fetch) generates a
structured audit event aligned with **NIST SP 800-53 AU-3** (Content of
Audit Records). Events capture *who*, *what*, *when*, *where*, *outcome*,
and *duration*.

### Configuration

```yaml
audit:
  enabled: true
  file: "logs/audit.jsonl"
  max_size_mb: 100
  backup_count: 5
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable audit event logging |
| `file` | string | `"logs/audit.jsonl"` | Path to JSONL audit log |
| `max_size_mb` | integer | `100` | Max file size before rotation (≥1 MB) |
| `backup_count` | integer | `5` | Number of rotated backups to keep (≥0) |

### Event Format

Each line in the audit log is a JSON object:

```json
{
  "timestamp": "2026-02-23T12:34:56.789000+00:00",
  "event_type": "mcp_operation",
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "source": {
    "session_id": "sess_abc123",
    "client_ip": "127.0.0.1",
    "user_id": "user@example.com"
  },
  "target": {
    "backend": "my-tool-server",
    "method": "call_tool",
    "capability_name": "search_files",
    "original_name": "search_files"
  },
  "outcome": {
    "status": "success",
    "latency_ms": 42.5,
    "error": null,
    "error_type": null
  },
  "metadata": {}
}
```

### Event Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | UTC ISO 8601 timestamp |
| `event_type` | string | Always `"mcp_operation"` |
| `event_id` | string | Unique event ID (UUID v4) |
| `source.session_id` | string | Client session identifier |
| `source.client_ip` | string | Client IP address |
| `source.user_id` | string | Authenticated user ID (if auth enabled) |
| `target.backend` | string | Backend server name |
| `target.method` | string | MCP method: `call_tool`, `read_resource`, `get_prompt` |
| `target.capability_name` | string | Exposed capability name |
| `target.original_name` | string | Original name at the backend |
| `outcome.status` | string | `"success"` or `"error"` |
| `outcome.latency_ms` | float | Request duration in milliseconds |
| `outcome.error` | string | Error message (if any) |
| `outcome.error_type` | string | Exception class name (if any) |

### Custom Log Level

Audit events use a custom log level `AUDIT = 35` (between WARNING=30 and
ERROR=40). This ensures audit records **cannot be silenced** by setting the
log level to WARNING or higher — a NIST requirement.

### File Rotation

The audit logger uses Python's `RotatingFileHandler`:

- When the log file reaches `max_size_mb`, it is renamed with a `.1` suffix
- Up to `backup_count` rotated files are kept
- Oldest files are automatically deleted
- UTF-8 encoding is enforced

### Integration

Audit events are emitted by the `AuditMiddleware` in the
[middleware chain](../middleware.md). The middleware wraps every request and
records both the request (pre) and response (post) as structured events.

---

## OpenTelemetry

Argus MCP supports optional OpenTelemetry (OTel) integration for
distributed tracing and metrics.

### Tracing

The `TelemetryMiddleware` creates a span per MCP request:

- **Span name:** `mcp.<method>.<capability_name>`
- **Attributes:** `mcp.method`, `mcp.capability`, `mcp.request_id`, `mcp.backend`
- Exceptions are recorded on the span
- Pass-through when `opentelemetry` is not installed

### Metrics

Request metrics are recorded via `record_request()`:

| Metric | Type | Labels |
|--------|------|--------|
| Request count | Counter | `tool_name`, `backend`, `success` |
| Request duration | Histogram | `tool_name`, `backend` |

### Setup

Install the OpenTelemetry packages:

```bash
pip install opentelemetry-api opentelemetry-sdk
```

Configure the OTel exporter via environment variables:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
export OTEL_SERVICE_NAME="argus-mcp"
```

When `opentelemetry` is not installed, the telemetry middleware degrades
gracefully to a no-op pass-through with zero overhead.

---

## Health Monitoring

Backend health is continuously monitored and exposed via the management API.

### Backend Lifecycle

Each backend tracks a 6-phase lifecycle:

```
Pending → Initializing → Ready → Degraded → Failed
                                     │
                                     ▼
                                ShuttingDown
```

| Phase | Description |
|-------|-------------|
| `Pending` | Registered but not yet started |
| `Initializing` | Connection/process startup in progress |
| `Ready` | Connected and healthy |
| `Degraded` | Responding but with health warnings |
| `Failed` | Disconnected or unresponsive |
| `ShuttingDown` | Graceful shutdown in progress |

### Health Checks

The `HealthChecker` periodically pings each backend and synchronizes the
backend status record. Health state transitions map to lifecycle phases:

- `healthy` → `Ready`
- `degraded` / `warning` → `Degraded`
- `unhealthy` / `error` → `Failed`

### Conditions

Each backend status record carries a list of `BackendCondition` entries
that provide fine-grained status details:

```json
{
  "type": "HealthCheckFailed",
  "status": true,
  "message": "Ping timeout after 10s",
  "last_transition": "2026-02-23T12:34:56Z"
}
```

### Management API

Backend health is exposed via:

- **`GET /manage/v1/health`** — Overall liveness (healthy/degraded/unhealthy)
- **`GET /manage/v1/backends`** — Per-backend status with phase, conditions, capabilities

See [Management API](../api/endpoints.md) for full details.

---

## Log Redaction

Resolved secrets are automatically scrubbed from all log output via the
`SecretRedactionFilter`. This prevents accidental exposure of API keys,
tokens, and passwords in log files.

- Filter is registered globally on all log handlers during `setup_logging()`
- Secrets are registered with the filter when resolved by the secret store
- Matched values are replaced with `[REDACTED]`
- Applies to message strings, dict arguments, and tuple arguments

See [Secrets Management](../security/secrets.md) for details on the secret store.
