# Builtin Plugins

Argus MCP ships with eight builtin plugins. Enable any of them by name in
your `config.yaml` under `plugins.entries`.

## secrets_detection

Scans request and response content for leaked secrets (API keys, tokens,
passwords). Blocks the request when a secret is found and `block` is
`true`.

An optional Rust-accelerated variant (`RustSecretsScanner`) is used
automatically when the native extension is available, falling back to the
pure-Python implementation otherwise.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `block` | boolean | `true` | Block requests containing secrets |

```yaml
- name: secrets_detection
  execution_mode: enforce
  priority: 10
  settings:
    block: true
```

## pii_filter

Detects and redacts personally identifiable information. Specify which
categories to scan for, or leave the list empty to scan all.

An optional Rust-accelerated variant (`RustPiiFilter`) is used when
available.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `categories` | list[string] | `[]` | PII categories to filter (empty = all) |

```yaml
- name: pii_filter
  priority: 15
  settings:
    categories: ["email", "phone", "ssn"]
```

## rate_limiter

Enforces request rate limits using a sliding window counter. Rejects
requests that exceed the threshold.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `max_requests` | integer | `100` | Maximum requests per window |
| `window` | integer | `60` | Window duration in seconds |

```yaml
- name: rate_limiter
  priority: 20
  settings:
    max_requests: 100
    window: 60
```

## circuit_breaker

Trips open after a threshold of consecutive failures. While open, requests
are rejected immediately until the cooldown elapses and the circuit resets.

An optional Rust-accelerated state machine (`circuit_breaker_rs`) is used
when the native extension is available.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `failure_threshold` | integer | `5` | Failures before tripping |
| `cooldown` | integer | `30` | Seconds before reset attempt |

```yaml
- name: circuit_breaker
  priority: 25
  settings:
    failure_threshold: 5
    cooldown: 30
```

## retry_with_backoff

Retries failed tool calls with exponential backoff and jitter. Only
retries on transient errors.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `max_retries` | integer | `3` | Maximum retry attempts |
| `base_delay` | float | `1.0` | Initial delay in seconds |
| `backoff` | float | `2.0` | Multiplier per retry |
| `max_delay` | float | `30.0` | Delay cap in seconds |

```yaml
- name: retry_with_backoff
  priority: 80
  settings:
    max_retries: 3
    base_delay: 1.0
    backoff: 2.0
    max_delay: 30.0
```

## response_cache_by_prompt

Caches tool responses keyed by the full prompt text. Reduces backend load
for repeated identical requests.

An optional Rust-accelerated cache key hasher (`hash_rs`) is used when
available. It combines JSON serialization and SHA-256 hashing in a single
FFI call, falling back to Python's `json.dumps` + `hashlib.sha256`
otherwise.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `ttl` | integer | `300` | Cache entry time-to-live in seconds |
| `max` | integer | `256` | Maximum cached entries |

```yaml
- name: response_cache_by_prompt
  priority: 30
  settings:
    ttl: 300
    max: 256
```

## output_length_guard

Truncates tool responses that exceed the maximum character length. Prevents
oversized payloads from reaching the client.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `max_length` | integer | `50000` | Maximum response length in characters |

```yaml
- name: output_length_guard
  priority: 90
  settings:
    max_length: 50000
```

## markdown_cleaner

Strips images, links, and HTML tags from markdown responses. Useful for
terminals or clients that do not render rich content.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `strip_images` | boolean | `true` | Remove image tags |
| `strip_links` | boolean | `true` | Remove hyperlinks |
| `strip_html` | boolean | `true` | Remove raw HTML |

```yaml
- name: markdown_cleaner
  priority: 95
  settings:
    strip_images: true
    strip_links: true
    strip_html: true
```

## Combined Example

```yaml
plugins:
  enabled: true
  entries:
    - name: secrets_detection
      execution_mode: enforce
      priority: 10
      settings:
        block: true

    - name: pii_filter
      priority: 15
      settings:
        categories: []

    - name: rate_limiter
      priority: 20
      settings:
        max_requests: 200
        window: 60

    - name: circuit_breaker
      priority: 25
      settings:
        failure_threshold: 5
        cooldown: 30

    - name: response_cache_by_prompt
      priority: 30
      settings:
        ttl: 300
        max: 256

    - name: retry_with_backoff
      priority: 80
      settings:
        max_retries: 3

    - name: output_length_guard
      priority: 90
      settings:
        max_length: 50000

    - name: markdown_cleaner
      priority: 95
```
