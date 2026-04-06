# Skills

Skills are **portable, self-contained bundles** of MCP tools, workflows, and
configuration. They act as a packaging mechanism: instead of manually adding
backends one-by-one, you install a skill that declares everything a particular
use-case needs.

> Skills are discovered automatically from the `skills/` directory in
> the project root, or from paths defined in your configuration.

---

## Concepts

| Term | Meaning |
|------|---------|
| **Skill** | A directory containing a `manifest.json` and optional supporting files |
| **Manifest** | JSON file declaring the skill's tools, workflows, config, and dependencies |
| **SkillManager** | Python class that discovers, installs, enables/disables, and uninstalls skills |
| **Apply** | Action that writes the skill's required backend entries to `config.yaml` and hot-reloads |

### How skills relate to backends

Skills are a *packaging layer* on top of backends. Each tool in a skill declares
which backend it needs (e.g. `"backend": "github"`). When you **Apply** a skill,
Argus writes those backends to `config.yaml` and triggers a hot-reload — no
restart required.

There is no separate "skill runtime." Applied skill tools are served by the
normal backend connection pipeline.

---

## Directory structure

```
skills/                           # Skills root (auto-detected: ./skills/ or examples/skills/)
├── code-search/
│   ├── manifest.json             # Required
│   ├── README.md                 # Optional
│   └── templates/                # Optional supporting files
├── github-integration/
│   └── manifest.json
└── skills-state.json             # Auto-generated: per-skill enabled/disabled state
```

---

## Manifest reference

Every skill directory must contain a `manifest.json`:

```jsonc
{
  // ── Required ──────────────────────────────
  "name": "my-skill",

  // ── Optional ──────────────────────────────
  "version": "1.0.0",            // semver, default "0.0.0"
  "description": "What this skill does",
  "author": "Your Name",
  "license": "GPL-3.0-only",

  // ── Tools ─────────────────────────────────
  "tools": [
    {
      "name": "search_code",
      "backend": "code-index",           // which backend serves this tool
      "description": "Full-text code search"
    }
  ],

  // ── Workflows ─────────────────────────────
  "workflows": [
    {
      "name": "deep-search",
      "description": "Search code and return matches with context",
      "steps": [
        {
          "id": "search",
          "tool": "code-index.search_code",
          "args": { "query": "${inputs.query}", "limit": 20 }
        },
        {
          "id": "context",
          "tool": "code-index.find_symbol",
          "depends_on": ["search"],
          "args": { "name": "${search.output.top_match}" }
        }
      ]
    }
  ],

  // ── Configuration ─────────────────────────
  "config": {
    "max_results": 50,
    "github_token": "${secrets.GITHUB_TOKEN}"   // secret reference
  },

  // ── Dependencies ──────────────────────────
  "dependencies": ["github"]       // names of other skills that must be installed
}
```

### Field details

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **yes** | Unique identifier (lowercase, hyphenated) |
| `version` | string | no | Semantic version, default `"0.0.0"` |
| `description` | string | no | Human-readable summary |
| `author` | string | no | Creator name |
| `license` | string | no | SPDX license identifier |
| `tools` | array | no | Tool definitions; each needs `name` and `backend` |
| `workflows` | array | no | Workflow definitions with DAG steps |
| `config` | object | no | Key-value defaults; supports `${secrets.KEY}` references |
| `dependencies` | array | no | Names of required skills (must be installed first) |

### Tool definition

Each entry in the `tools` array:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Tool name (unique within the skill) |
| `backend` | string | Backend name that serves this tool |
| `description` | string | What the tool does |

### Workflow definition

See [docs/workflows/](../workflows/) for full workflow documentation.

---

## Using skills in the TUI

### Browse & manage

1. Launch: `argus-mcp tui`
2. Switch to **Skills** mode (key shown in footer, typically `5`)
3. The screen auto-discovers skills from `./skills/` or `examples/skills/`

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus search input |
| `e` | Toggle Enable / Disable |
| `a` | Apply skill (write backends to config) |
| `u` | Uninstall skill |
| `Escape` | Back to previous screen |

### What "Apply" does

1. Reads each tool's `backend` field from the manifest.
2. For each backend, writes a `backends.<name>` entry to `config.yaml`.
3. Triggers a hot-reload via the management API.
4. The backend connects and the skill's tools become available immediately.

---

## Using skills programmatically

```python
from argus_mcp.skills import SkillManager, SkillStatus

manager = SkillManager(skills_dir="skills")

# Discover all skills
manager.discover()

# List
for skill in manager.list_skills():
    print(f"{skill.name} v{skill.manifest.version} [{skill.status.value}]")

# Install from a directory
manager.install("examples/skills/code-search")

# Enable / disable
manager.enable("code-search")
manager.disable("code-search")

# Get tools from all enabled skills
tools = manager.get_all_tools()
for t in tools:
    print(f"  {t['name']} (backend: {t['backend']}, skill: {t['_skill']})")

# Get workflows
workflows = manager.get_all_workflows()

# Uninstall
manager.uninstall("code-search")
```

---

## Creating your own skill

### Step 1 — Create the directory

```bash
mkdir -p skills/my-awesome-skill
```

### Step 2 — Write `manifest.json`

```json
{
  "name": "my-awesome-skill",
  "version": "1.0.0",
  "description": "Does awesome things",
  "author": "you",
  "license": "GPL-3.0-only",
  "tools": [
    {
      "name": "do_awesome_thing",
      "backend": "awesome-server",
      "description": "Performs the awesome action"
    }
  ],
  "config": {
    "api_key": "${secrets.AWESOME_API_KEY}"
  },
  "dependencies": []
}
```

### Step 3 — Install and enable

In the TUI, navigate to Skills, and the manager will auto-discover it. Or
programmatically:

```python
manager.install("skills/my-awesome-skill")
manager.enable("my-awesome-skill")
```

### Step 4 — Apply

Press `a` in the TUI, or write the backend config manually. The `awesome-server`
backend must be connectable (stdio command, SSE URL, etc.).

---

## State persistence

Enabled/disabled state is saved to `skills-state.json` next to the skills
directory:

```json
{
  "code-search": "enabled",
  "github-integration": "disabled"
}
```

This file is auto-managed by `SkillManager`. Don't edit it by hand.

---

## Example skills

Two example skills ship with the project in
[examples/skills/](../../examples/skills/):

### `code-search`

| Field | Value |
|-------|-------|
| Tools | `search_code`, `find_symbol`, `list_files` |
| Backend | `code-index` |
| Workflows | `deep-search` (search → find symbol) |

### `github-integration`

| Field | Value |
|-------|-------|
| Tools | `list_issues`, `get_issue`, `triage_issue`, `list_pull_requests`, `summarise_pr` |
| Backend | `github` |
| Workflows | `issue-triage` (fetch → classify), `pr-summary` (list → summarise) |
| Config | `github_token: ${secrets.GITHUB_TOKEN}`, `default_repo: owner/repo` |
| Dependencies | `github` |

---

## Module map

| Module | Purpose |
|--------|---------|
| `argus_mcp/skills/__init__.py` | Package exports |
| `argus_mcp/skills/manifest.py` | `SkillManifest` dataclass + JSON parsing/validation |
| `argus_mcp/skills/manager.py` | `SkillManager` lifecycle (discover, install, enable, apply, uninstall) |
| `argus_mcp/tui/screens/skills.py` | TUI Skills screen |
| `examples/skills/` | Example skill packages |
