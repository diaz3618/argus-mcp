# Naming & Style Conventions Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` (160 files, 28,965 lines)
**Tools:** Ruff format, Grep, Manual inspection

---

## Ruff Formatting Violations (12 files)

The following files would be reformatted by `ruff format`:

### Bridge Layer (3 files)

1. **`argus_mcp/bridge/capability_registry.py`** -- Capability registry
2. **`argus_mcp/bridge/conflict.py`** -- Conflict resolution
3. **`argus_mcp/bridge/middleware/audit.py`** -- Audit middleware

### Server Layer (4 files)

4. **`argus_mcp/server/handlers.py`** -- Request handlers
5. **`argus_mcp/server/management/auth.py`** -- Management auth
6. **`argus_mcp/server/origin.py`** -- Origin handling
7. **`argus_mcp/server/transport.py`** -- Transport layer

### Display Layer (2 files)

8. **`argus_mcp/display/console.py`** -- Console display
9. **`argus_mcp/display/logging_config.py`** -- Logging configuration

### TUI (2 files)

10. **`argus_mcp/tui/screens/backend_detail.py`** -- Backend detail screen
11. **`argus_mcp/tui/screens/health.py`** -- Health screen

### Workflows (1 file)

12. **`argus_mcp/workflows/dsl.py`** -- Workflow DSL

- **Tool:** `ruff format --check argus_mcp/`
- **Suggested fix:** Run `ruff format argus_mcp/` to auto-format all files.

---

## Naming Inconsistencies

### [MEDIUM] `svr_name` vs `server_name` vs `backend_name`

- **Files:** Pervasive across codebase
- **Tool:** Grep
- **Rule:** naming-inconsistency
- **Description:** The same concept (a backend server identifier) uses three different names:
  - `svr_name` -- 269 occurrences (dominant in `client_manager.py`, `capability_registry.py`)
  - `backend_name` -- 65 occurrences (used in `auth/store.py`, `auth/provider.py`)
  - `server_name` -- 54 occurrences (used in `conflict.py`, `transport.py`, `session/models.py`)
- **Evidence:** `bridge/client_manager.py` alone has the majority of `svr_name` usage, while `auth/store.py` uses `backend_name` exclusively for the same concept. Total: 386 occurrences across the codebase with no consistent choice.
- **Suggested fix:** Standardize on `backend_name` throughout (most descriptive), or at minimum `server_name` (most conventional). `svr_name` is an unnecessary abbreviation.

### [LOW] `app_s` abbreviation

- **File:** `argus_mcp/server/lifespan.py`, `argus_mcp/cli.py`
- **Tool:** Grep
- **Rule:** naming-clarity
- **Description:** `app_s = app.state` is an unclear abbreviation. No occurrences found in current working tree (may have been refactored), but the pattern existed previously.
- **Suggested fix:** Use `app_state` instead of `app_s` if reintroduced.

### [LOW] `cfg_abs_path` vs `config_path` vs `cfg_path`

- **Files:** `cli.py`, `lifespan.py`, `service.py`, `loader.py`
- **Tool:** Grep
- **Rule:** naming-inconsistency
- **Description:** Config file paths use three different variable names:
  - `config_path` -- 88 occurrences (dominant)
  - `cfg_path` -- 5 occurrences
  - `cfg_abs_path` -- 4 occurrences
- **Suggested fix:** Standardize on `config_path` (already dominant). Replace `cfg_path` and `cfg_abs_path`.

### [LOW] `_YAML_EXTS` as tuple vs list

- **File:** `argus_mcp/server/lifespan.py`
- **Tool:** Manual
- **Rule:** type-consistency
- **Description:** `_YAML_EXTS = (".yaml", ".yml")` is a tuple while similar constants elsewhere use lists. Minor but inconsistent.

### [LOW] Hungarian notation remnants

- **File:** `argus_mcp/cli.py`
- **Tool:** Grep
- **Rule:** naming-style
- **Description:** Exception variables use a `e_` prefix convention not seen elsewhere:
  - `e_bind` (line 115)
  - `e_exit` (line 128)
  - `e_serve` (line 130)
  - `e_sys_exit` (line 315)
  - `e_fatal` (lines 328, 562)
  - `e_imp` (line 553)
- **Evidence:** 7 instances in `cli.py`. Most Python code uses `exc` or descriptive names like `config_err`.
- **Suggested fix:** Standardize on `exc` or descriptive names like `bind_err`, `serve_err`.

### [LOW] Private method naming: leading underscore inconsistency

- **Files:** Various
- **Tool:** Manual
- **Rule:** naming-convention
- **Description:** Some internal helper functions use `_` prefix while others don't. Convention is inconsistent for helper functions within classes.

---

## Docstring Coverage

### [LOW] Mixed docstring styles (NumPy vs Google)

- **Files:** Various
- **Tool:** Grep
- **Rule:** docstring-style
- **Description:** The codebase mixes NumPy-style and Google-style docstrings:
  - NumPy-style (`Parameters\n----------`): 56 occurrences across `config/diff.py`, `config/client_gen.py`, `config/flags.py`, `config/watcher.py`, `server/session/manager.py`, `server/auth/oidc.py`, `server/authz/engine.py`, `bridge/middleware/` modules
  - Google-style (`Args:`): 5 occurrences in `bridge/middleware/chain.py`, `bridge/capability_registry.py`, `display/logging_config.py`, `tui/widgets/server_groups.py`
  - Plain (`Returns:`, `Raises:`): 5 occurrences in `config/loader.py`, `bridge/auth/pkce.py`, `runtime/service.py`
- **Suggested fix:** Standardize on NumPy-style (dominant at 56 occurrences) project-wide.

### [LOW] Missing docstrings on TUI handlers

- **Files:** Various TUI widgets and screens
- **Tool:** Manual
- **Rule:** missing-docstring
- **Description:** Many `on_button_pressed`, `on_mount`, `on_show` handlers lack docstrings. While Textual convention doesn't require them, they aid understanding in a large TUI codebase.

---

## Import Style

### [LOW] Deferred imports in function bodies (40+ instances)

- **Files:** `lifespan.py` (20+), `cli.py`, `service.py`, `router.py`, `app.py`, `transport.py`, `jwt.py`, `oidc.py`, `providers.py`, `recovery.py`, `checker.py`
- **Tool:** Grep
- **Rule:** import-style
- **Description:** 40+ deferred imports (`from X import Y` inside function bodies) used to avoid circular imports. `lifespan.py` alone has 20+ deferred imports. While sometimes necessary, this pattern makes dependencies opaque and increases import-time risk.
- **Key offenders:**
  - `server/lifespan.py`: 20+ deferred imports including `yaml`, `pathlib.Path`, middleware, config, audit, and session modules
  - `server/management/router.py`: 4 deferred imports
  - `server/transport.py`: 2 deferred imports of `mcp_server` from `app`
  - `server/auth/jwt.py`: deferred `import jwt`
- **Suggested fix:** Consider restructuring to reduce circular dependencies, or use `TYPE_CHECKING` blocks for type-only imports.

---

## Type Annotation Gaps

### [LOW] `Any` overuse (77 instances)

- **Files:** Pervasive across codebase
- **Tool:** Grep (`: Any`)
- **Rule:** type-safety
- **Description:** 77 uses of `: Any` type annotations where more specific types may be known:
  - `mcp_svr_instance: Any` -- should be `FastMCP` or the actual server type
  - `self._server_manager: Optional[object]` -- should be `Optional[ServerManager]`
  - `self._last_status: Optional[Any]` -- should be `Optional[StatusResponse]`
- **Suggested fix:** Audit each `Any` annotation and replace with specific types where the type is known.

### [LOW] `type: ignore` comments (37 instances)

- **Files:** Various
- **Tool:** Grep
- **Rule:** unused-ignore
- **Description:** 37 `type: ignore` comments across the codebase. Some may be necessary for third-party library type stubs, but others may be stale or unnecessary.
- **Suggested fix:** Run mypy with `--warn-unused-ignores` to identify removable instances.

---

## Summary

| Category | Count |
|----------|-------|
| Ruff formatting violations | 12 files |
| Naming inconsistencies | 6 patterns (386 total occurrences for server name alone) |
| Docstring issues | 2 patterns (mixed NumPy/Google/plain) |
| Import style issues | 40+ deferred imports |
| Type annotation gaps | 77 `Any` annotations, 37 `type: ignore` |
| **Total convention findings** | **6 MEDIUM, 10+ LOW** |
