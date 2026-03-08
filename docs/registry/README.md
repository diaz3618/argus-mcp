# MCP Server Registry

The **Registry** feature lets you browse, search, and install MCP servers from
one or more remote catalogs directly inside the TUI (or programmatically via the
registry client).

---

## Quick start

1. Add at least one registry to your `config.yaml` (see [Configuring registries](#configuring-registries)).
2. Launch the TUI: `argus-mcp tui`
3. Press the key binding for **Registry** mode (shown in the footer).
4. The browser fetches the server list from your configured registries.
5. Use the search box to filter by name or description.
6. Select a server → review details in the right panel → press **Install**.
7. The server definition is written to your `config.yaml` as a new `backends`
   entry and a hot-reload is triggered automatically.

---

## Architecture overview

```
┌──────────────────────────────────────────────────────────────────┐
│                       RegistryScreen                             │
│  ┌─────────────────────────┐  ┌────────────────────────────────┐ │
│  │  RegistryBrowserWidget  │  │      InstallPanelWidget        │ │
│  │  (searchable DataTable) │  │  (detail + Install button)     │ │
│  │                         │  │                                │ │
│  │  Name│Transport│Tools   │  │  Name: my-server               │ │
│  │  ────│─────────│─────   │  │  Transport: stdio              │ │
│  │  ... │  stdio  │  12    │  │  Command: uvx my-server        │ │
│  └─────────────────────────┘  │  Tools: list_files, read_...   │ │
│                               │                                │ │
│                               │  [Install]                     │ │
│                               └────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
  RegistryClient ──────────── RegistryCache
    (httpx)          miss?     (~/.cache/argus-mcp/registry/)
         │
         ▼
  Registry API  (GET /v0/servers)
  (user-configured URL)
```

### Module map

| Module | Purpose |
|--------|---------|
| `argus_mcp/registry/client.py` | Async HTTP client (`httpx`) hitting the registry API |
| `argus_mcp/registry/models.py` | `ServerEntry`, `ToolDefinition`, `ServerPage` dataclasses |
| `argus_mcp/registry/cache.py` | File-backed JSON cache (`~/.cache/argus-mcp/registry/`, 300 s TTL) |
| `argus_mcp/config/schema_registry.py` | `RegistryEntryConfig` Pydantic model |
| `argus_mcp/tui/screens/registry.py` | TUI screen: wires browser + install panel |
| `argus_mcp/tui/widgets/registry_browser.py` | Searchable `DataTable` of servers |
| `argus_mcp/tui/widgets/install_panel.py` | Right-side detail + install button |
| `argus_mcp/tui/screens/server_detail.py` | Full-screen modal for detailed tool listing |

---

## Registry API

The client expects a REST endpoint that implements the `/v0/servers` contract
described below. Any HTTP server returning the correct JSON shapes will work.

### Endpoints used

| Method | Path | Query params | Response |
|--------|------|--------------|----------|
| GET | `/v0/servers` | `limit`, `cursor`, `q` (search) | `ServerPage` JSON |
| GET | `/v0/servers/{name}` | — | Single `ServerEntry` JSON |

### `ServerEntry` JSON shape

```jsonc
{
  "name": "example-server",
  "description": "An example MCP server",
  "transport": "stdio",            // "stdio" | "sse" | "streamable-http"
  "command": "uvx example-server", // for stdio
  "args": ["--flag"],              // optional, for stdio
  "url": "",                       // for sse / streamable-http
  "version": "1.2.0",
  "icon_url": "",
  "categories": ["search", "coding"],
  "tools": [
    {
      "name": "list_files",
      "description": "List files in a directory",
      "inputSchema": { "type": "object", "properties": { ... } }
    }
  ]
}
```

### `ServerPage` JSON shape

```jsonc
{
  "servers": [ ... ],      // array of ServerEntry
  "next_cursor": "abc123", // null when no more pages
  "total": 42              // optional count
}
```

---

## Configuring registries

No registries are included by default. You must add the registries you want to
use. There are two ways to configure them:

### Option 1: `config.yaml` (recommended)

Add a `registries` section to your `config.yaml`:

```yaml
registries:
  - name: community
    url: "https://glama.ai/api/mcp"
    priority: 100
    auth: none

  - name: smithery
    url: "https://registry.smithery.ai"
    priority: 200
    auth: none

  - name: internal
    url: "https://registry.corp.example.com/v0/servers"
    priority: 50
    auth: api-key
    api_key_env: INTERNAL_REGISTRY_KEY   # reads from environment variable
```

#### `RegistryEntryConfig` fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | **required** | Friendly label (e.g. `"community"`, `"internal"`) |
| `url` | string | **required** | Base URL of the registry API |
| `priority` | int | `100` | Lower number = checked first |
| `auth` | `"none"` \| `"api-key"` \| `"bearer"` | `"none"` | Authentication type |
| `api_key_env` | string | — | Environment variable for API key (when `auth: api-key`) |
| `token_env` | string | — | Environment variable for bearer token (when `auth: bearer`) |

### Option 2: TUI Settings → Registries tab

You can also manage registries from **Settings → Registries** in the TUI.
These are persisted to the TUI's local `settings.json` file.

The TUI settings and `config.yaml` are merged at runtime.
`config.yaml` registries are checked first, followed by TUI settings entries.

### Resolution order

1. TUI settings (`settings.json`) registries, sorted by priority
2. `config.yaml` `registries` section, sorted by priority
3. If neither has entries → the Registry screen shows a "No registries configured" message

---

## Known public registries

The following registries are known to implement (or partially implement) the
`/v0/servers` API contract. **None of these are bundled or hardcoded.** Add the
ones you want to use in your `config.yaml`.

| Registry | API URL | Catalog size | Auth | Notes |
|----------|---------|-------------|------|-------|
| [Glama.ai](https://glama.ai/mcp/servers) | `https://glama.ai/api/mcp` | 17,800+ servers | None (public) | Curated directory, community submissions |
| [Smithery.ai](https://smithery.ai) | `https://registry.smithery.ai` | 4,500+ MCPs | None (public) | CLI-first (`@smithery/cli`), built-in OAuth |
| [mcpservers.org](https://mcpservers.org) | — | Community directory | — | No REST API (browse only) |
| [Composio](https://mcp.composio.dev) | — | 100+ SaaS connectors | — | Managed MCP integrations |
| [OpenTools](https://opentools.com) | `https://api.opentools.com` | — | — | API gateway, OpenAI-compatible |

> **Compatibility note:** Not all public registries implement the exact
> `/v0/servers` contract. The RegistryClient expects `ServerPage` and
> `ServerEntry` JSON shapes. Verify the endpoint returns compatible responses
> before adding it.

---

## Installation flow

When you press **Install** on a registry server:

1. `ServerEntry.to_backend_config()` converts the entry to a backend config
   dict matching Argus's config format:

   | Transport | Generated config |
   |-----------|-----------------|
   | `stdio` | `{"type": "stdio", "command": "...", "args": [...]}` |
   | `sse` | `{"type": "sse", "url": "..."}` |
   | `streamable-http` | `{"type": "streamable-http", "url": "..."}` |

2. The config dict is written to `config.yaml` under `backends.<server-name>`.

3. A hot-reload is triggered via the management API, so the new backend starts
   connecting without a server restart.

### Example

Installing a server called `"mcp-github"` with transport `stdio` adds:

```yaml
backends:
  # ... existing backends ...
  mcp-github:
    type: stdio
    command: uvx mcp-github
    args: []
```

---

## Cache

API responses are cached to `~/.cache/argus-mcp/registry/` as JSON files
(one per registry URL). The cache has a **300-second TTL** — after that, the
next request re-fetches from the API. On network failure, the client
transparently falls back to the cache.

To clear the cache manually:

```bash
rm -rf ~/.cache/argus-mcp/registry/
```

---

## Running your own registry

If you want to serve a private registry:

1. **Build a compatible API** — any HTTP server that returns the JSON shapes
   above at `GET /v0/servers` will work. The client only requires:
   - `GET /v0/servers` (list/paginate)
   - `GET /v0/servers/{name}` (single entry)

2. **Static file approach** — for a tiny catalog, serve a static `servers.json`:

   ```json
   {
     "servers": [
       {
         "name": "my-internal-tool",
         "description": "Internal analysis tool",
         "transport": "stdio",
         "command": "uvx my-internal-tool",
         "version": "0.3.0",
         "tools": []
       }
     ],
     "total": 1
   }
   ```

   Host it behind nginx/caddy at `https://internal.example.com/v0/servers`.

3. **Add it to your config:**

   ```yaml
   registries:
     - name: internal
       url: "https://internal.example.com"
       priority: 10
       auth: none
   ```
