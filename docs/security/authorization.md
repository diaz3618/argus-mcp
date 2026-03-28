# Authorization (RBAC)

Argus MCP supports Role-Based Access Control (RBAC) for fine-grained
permission management. When enabled, every MCP operation is evaluated against
a set of authorization policies.

## Configuration

```yaml
authorization:
  enabled: true
  default_effect: deny          # "allow" or "deny" when no policy matches
  policies:
    - effect: allow
      roles: ["admin"]
      resources: ["*"]

    - effect: allow
      roles: ["developer"]
      resources: ["tool:search_*", "resource:docs/*", "prompt:*"]

    - effect: deny
      roles: ["*"]
      resources: ["tool:dangerous_*"]
```

## Policy Fields

| Field | Type | Description |
|-------|------|-------------|
| `effect` | `"allow"` or `"deny"` | Grant or deny access |
| `roles` | list[string] | Roles this policy applies to. `"*"` matches all roles |
| `resources` | list[string] | Resource patterns to match (glob-supported) |
| `description` | string | Optional human-readable description |

## Resource Identifiers

Resources are formatted as `type:name`:

| Format | Example | Matches |
|--------|---------|---------|
| `tool:<name>` | `tool:search_web` | Specific tool |
| `tool:*` | — | All tools |
| `tool:search_*` | — | Tools matching glob |
| `resource:<uri>` | `resource:docs/readme` | Specific resource |
| `prompt:<name>` | `prompt:code_review` | Specific prompt |
| `server:<name>` | `server:my-backend` | Specific backend server |
| `group:<name>` | `group:search-tools` | A server group |
| `*` | — | Everything |

## Evaluation Logic

```
Request arrives with UserIdentity (from auth middleware)
  │
  ├─ For each policy (in order):
  │   ├─ Does user have any matching role?
  │   └─ Does the resource match?
  │       ├─ YES → Apply the policy's effect (allow/deny) → DONE
  │       └─ NO  → Continue to next policy
  │
  └─ No policy matched → Apply default_effect
```

- Policies are evaluated in order — first match wins
- Glob patterns are supported for resources (via `fnmatch`)
- Roles come from the JWT claims (`roles` or `realm_access.roles`)

## Role Sources

Roles are extracted from the authenticated user's identity:

| Auth Type | Role Source |
|-----------|-------------|
| `anonymous` | Empty (no roles) |
| `local` | Empty (no roles) |
| `jwt` | `roles` claim or `realm_access.roles` |
| `oidc` | Same as JWT |

## Examples

### Admin-only access

```yaml
authorization:
  enabled: true
  default_effect: deny
  policies:
    - effect: allow
      roles: ["admin"]
      resources: ["*"]
```

### Read-only for viewers, full access for developers

```yaml
authorization:
  enabled: true
  default_effect: deny
  policies:
    - effect: allow
      roles: ["viewer"]
      resources: ["resource:*", "prompt:*"]
    - effect: allow
      roles: ["developer"]
      resources: ["*"]
```

### Deny dangerous tools for everyone

```yaml
authorization:
  enabled: true
  default_effect: allow
  policies:
    - effect: deny
      roles: ["*"]
      resources: ["tool:delete_*", "tool:drop_*"]
```

## Middleware Integration

The `AuthzMiddleware` is implemented in `argus_mcp.bridge.middleware.authz`
but is **not currently wired** into the default middleware chain built by
`_build_middleware_stack()`. To enable it, add it to the chain manually
via `build_chain()` after `AuthMiddleware`.

When activated, it sits after `AuthMiddleware` in the chain:

1. Reads `UserIdentity` from `ctx.metadata["user"]`
2. Builds the resource identifier (e.g., `tool:search_web`)
3. Evaluates policies via the `PolicyEngine`
4. On allow: passes to next middleware
5. On deny: raises `AuthorizationError` (HTTP 403)

If authorization is disabled (`enabled: false`), the middleware is a no-op
pass-through.
