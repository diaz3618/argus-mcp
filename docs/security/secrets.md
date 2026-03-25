# Secrets Management

Argus MCP provides an encrypted secret store for managing sensitive values
like API keys, tokens, and credentials. Secrets are referenced in config files
and resolved at startup — they never appear in plaintext in config or logs.

## Architecture

```
Config file                    SecretStore
  │                               │
  │  secret:my-api-key        ┌───┴─────────────────┐
  │  ─────────────────►       │  SecretResolver     │
  │                           │                     │
  │                           │  Looks up in:       │
  │                           │  ├─ FileProvider    │
  │                           │  ├─ EnvProvider     │
  │                           │  └─ KeyringProvider │
  │                           │                     │
  │  sk-abc123...             │  Registers with:    │
  │  ◄─────────────────       │  LogRedactionFilter │
  │                           └─────────────────────┘
```

## Providers

### File Provider (default)

Stores secrets in a Fernet-encrypted JSON file.

| Setting | Value |
|---------|-------|
| **File** | `secrets.enc` (configurable via `--path`) |
| **Encryption** | Fernet (AES-128-CBC + HMAC-SHA256) |
| **Master key** | `ARGUS_SECRET_KEY` environment variable |
| **File permissions** | `0600` (owner read/write only) |
| **Write strategy** | Atomic (temp file + rename) |
| **Dependency** | `cryptography` package |

```bash
# Generate a master key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export ARGUS_SECRET_KEY="<generated-key>"

# Store secrets
argus-mcp secret set my-api-key
argus-mcp secret set db-password
```

### Environment Provider

Maps secret names to environment variables using a convention:

```
secret name:  my-api-key
env var:      SECRET_MY_API_KEY
```

Convention: uppercase, hyphens → underscores, `SECRET_` prefix.

```bash
export SECRET_MY_API_KEY=sk-abc123
```

### Keyring Provider

Uses the OS-native credential store:

| OS | Backend |
|----|---------|
| macOS | Keychain |
| Linux | GNOME Keyring / KWallet |
| Windows | Credential Locker |

Service name: `argus-mcp`. Requires the `keyring` package.

## Config Integration

Reference secrets with the `secret:` prefix in any config string value:

```yaml
backends:
  my-server:
    type: sse
    url: "http://localhost:8080/sse"
    headers:
      Authorization: "Bearer secret:my-api-key"

server:
  management:
    token: "secret:mgmt-token"

incoming_auth:
  type: local
  token: "secret:auth-token"
```

### Resolution Process

1. Config is loaded and parsed
2. `resolve_secrets()` walks all string values
3. Strings matching `^secret:(.+)$` are looked up in the SecretStore
4. Resolved values replace the references in-memory
5. Each resolved value is registered with the `SecretRedactionFilter`

### Strict Mode

```python
resolve_secrets(config, store, strict=True)   # raises on missing
resolve_secrets(config, store, strict=False)  # logs warning, keeps reference
```

## Log Redaction

All resolved secret values are automatically registered with the
`SecretRedactionFilter`:

- The filter is attached to all log handlers at startup
- Any log message containing a secret value has it replaced with `***REDACTED***`
- Redaction uses compiled regex patterns for performance
- Works on string messages, dict args, and tuple args

This ensures no plaintext secrets appear in:

- Application log files
- Console output
- Audit trail messages

## CLI Reference

See [`argus-mcp secret`](../cli/secret.md) for the command-line interface.

## SecretStore API

```python
from argus_mcp.secrets.store import SecretStore

store = SecretStore(provider_type="file", path="secrets.enc")

# CRUD operations
store.set("my-key", "my-value")
value = store.get("my-key")
names = store.list_names()
store.delete("my-key")
exists = store.exists("my-key")
```
