# Outgoing Authentication

Argus MCP can authenticate to backend MCP servers using static headers or
OAuth 2.0 client credentials. This applies to SSE and Streamable HTTP backends.

## Static Headers

Inject fixed headers into every request to the backend:

```yaml
backends:
  my-server:
    type: sse
    url: "http://backend:8080/sse"
    auth:
      type: static
      headers:
        Authorization: "Bearer ${API_KEY}"
        X-Custom-Header: "value"
```

Header values support `${ENV_VAR}` expansion and `secret:name` resolution.

## OAuth 2.0 Client Credentials

Automatically obtain and refresh access tokens using the OAuth 2.0 client
credentials grant:

```yaml
backends:
  my-server:
    type: streamable-http
    url: "http://backend:8080/mcp"
    auth:
      type: oauth2
      token_url: "https://auth.example.com/oauth/token"
      client_id: "argus-client"
      client_secret: "${OAUTH_CLIENT_SECRET}"
      scopes:
        - mcp:read
        - mcp:write
```

| Field | Required | Description |
|-------|----------|-------------|
| `token_url` | Yes | OAuth 2.0 token endpoint URL |
| `client_id` | Yes | Client identifier |
| `client_secret` | Yes | Client secret (supports `${ENV_VAR}` and `secret:name`) |
| `scopes` | No | Requested OAuth scopes (default: empty) |

### Token Management

- Tokens are cached in memory with `TokenCache`
- Near-expiry tokens are refreshed automatically (buffer before TTL)
- Token fetch uses `asyncio.Lock` with double-check pattern to prevent
  thundering herd (multiple concurrent requests all trying to refresh)
- HTTP requests to the token endpoint have a 30-second timeout
- The `Authorization: Bearer <token>` header is injected into backend requests

### Error Handling

If token acquisition fails:

- The error is logged
- The backend request proceeds without authentication
- The backend may reject the request (depends on backend's auth requirements)

## OAuth 2.0 Authorization Code + PKCE

For MCP servers that require interactive browser-based login (e.g. Semgrep,
GitHub Copilot), use the PKCE auth type. On first use Argus opens a browser
for the user to authenticate and then caches and refreshes the token
automatically.

```yaml
backends:
  semgrep:
    type: streamable-http
    url: "https://mcp.semgrep.ai/mcp"
    auth:
      type: pkce
      authorization_endpoint: "https://auth.semgrep.dev/authorize"
      token_endpoint: "https://auth.semgrep.dev/oauth/token"
      client_id: "${SEMGREP_CLIENT_ID}"
      scopes:
        - openid
        - profile
```

| Field | Required | Description |
|-------|----------|-------------|
| `authorization_endpoint` | Yes | OAuth 2.0 authorization URL |
| `token_endpoint` | Yes | OAuth 2.0 token endpoint URL |
| `client_id` | Yes | Client identifier (supports `${ENV_VAR}`) |
| `client_secret` | No | Client secret (empty for public clients) |
| `scopes` | No | Requested OAuth scopes (default: empty) |

### PKCE Token Flow

1. **Cache check** — in-memory first, then disk (`~/.config/argus-mcp/tokens/`)
2. **Refresh** — if a `refresh_token` is on disk but the access token expired,
   Argus refreshes silently without user interaction.
3. **Browser flow** — if no valid token exists, Argus starts a local HTTP
   callback server on `127.0.0.1` (ephemeral port), opens the browser, and
   waits up to 120 seconds for the user to complete login.
4. **Persistence** — the new token set is written to disk with `0600`
   permissions and cached in memory.

### Security

- PKCE S256 challenge protects against authorization code interception
- State parameter prevents CSRF attacks
- Token files use restricted `0600` permissions (owner-only read/write)
- Callback server binds only to `127.0.0.1` (localhost)

## No Auth

If no `auth` block is specified, no authentication headers are added to backend
requests. Additional headers can still be set via the `headers` field:

```yaml
backends:
  public-server:
    type: sse
    url: "http://public-backend:8080/sse"
    headers:
      X-Request-Source: "argus"
```
