# Management API

Argus MCP exposes a REST API at `/manage/v1/` for monitoring, inspecting,
and controlling the gateway at runtime.

## Base URL

```
http://<host>:<port>/manage/v1/
```

Default: `http://127.0.0.1:9000/manage/v1/`

## Authentication

The management API uses bearer token authentication:

```bash
curl -H "Authorization: Bearer $ARGUS_MGMT_TOKEN" \
     http://localhost:9000/manage/v1/status
```

Token configuration:

- Config: `server.management.token`
- Env: `ARGUS_MGMT_TOKEN`
- If no token is configured, the API is open (no auth)
- `GET /health` is always public (no token required)

## Endpoints

See [Endpoint Reference](endpoints.md) for the complete API specification.

### Quick Overview

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | Public | Liveness / readiness probe |
| `/ready` | GET | Public | Readiness probe (503 until backends connect) |
| `/status` | GET | Token | Full service status |
| `/backends` | GET | Token | Backend connection states |
| `/groups` | GET | Token | Logical server groups |
| `/capabilities` | GET | Token | Aggregated tools/resources/prompts |
| `/sessions` | GET | Token | Active client sessions |
| `/events` | GET | Token | Recent events (polling) |
| `/events/stream` | GET | Token | Real-time event SSE stream |
| `/batch` | GET | Token | Combined status/backends/capabilities/events |
| `/reload` | POST | Token | Hot-reload config |
| `/reconnect/{name}` | POST | Token | Reconnect a backend |
| `/reauth/{name}` | POST | Token | Re-authenticate a backend |
| `/shutdown` | POST | Token | Graceful shutdown |
| `/registry/search` | GET | Token | Search external MCP server registries |
| `/skills` | GET | Token | List all discovered skills |
| `/skills/{name}/enable` | POST | Token | Enable a skill |
| `/skills/{name}/disable` | POST | Token | Disable a skill |
| `/tools/call` | POST | Token | Proxy MCP tools/call to backend |
| `/resources/read` | POST | Token | Proxy MCP resources/read to backend |

## Error Responses

All error responses follow this format:

```json
{
  "error": "error_code",
  "message": "Human-readable description",
  "details": {}
}
```

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 401 | Missing or invalid bearer token |
| 404 | Backend not found (for `/reconnect/{name}`) |
| 500 | Internal server error |
