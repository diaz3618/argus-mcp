# Duplicate / Copy-Paste Code Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI (159+ files, ~29K lines)
**Tools:** Grep pattern analysis, Manual inspection

---

## Pattern 1: `except Exception: pass` in TUI Widget Updates

### [MEDIUM] Widget-not-in-active-screen silencing pattern

- **Files:** `argus_mcp/tui/app.py` (30 occurrences of `except Exception`)
- **Tool:** Grep (`grep -c 'except Exception' argus_mcp/tui/app.py` = 30)
- **Rule:** duplicate-pattern
- **Description:** The identical pattern `try: widget = self.screen.query_one(SomeWidget); widget.do_something(); except Exception: pass` is repeated across `_apply_status_response`, `_apply_backends_response`, `_apply_capabilities_response`, `_apply_events_response`, `on_connection_lost`, `on_connection_restored`, `on_config_sync_update`, `_refresh_server_selector`, and theme-related handlers. Each block catches all exceptions and silently discards them.
- **Evidence:** Lines 283, 301, 342, 408, 490, 518, 548, 558, 567, 583, 592, 618, 653, 668, 707, 716, 742, 751, 765, 774, 816, 830, 840, 850, 861, 870 (and more).
  ```python
  # Repeated 20+ times with minor variations:
  try:
      widget = self.screen.query_one(ServerInfoWidget)
      widget.update(...)
  except Exception:
      pass  # Widget not in active screen
  ```
- **Suggested fix:** Extract a helper method:
  ```python
  def _try_widget(self, widget_type, callback):
      try:
          w = self.screen.query_one(widget_type)
          callback(w)
      except Exception:
          pass
  ```

---

## Pattern 2: Config File Discovery Logic

### [MEDIUM] Duplicated config file search across 5+ locations

- **Files:**
  - `argus_mcp/config/loader.py:37-54` (`find_config_file()`) -- canonical implementation
  - `argus_mcp/tui/screens/setup_wizard.py:108-118` (`_find_config_path()`) -- separate implementation
  - `argus_mcp/tui/screens/tool_editor.py:296` -- inline `for name in ("config.yaml", "config.yml")`
  - `argus_mcp/tui/screens/skills.py:467` -- inline `for name in ("config.yaml", "config.yml")`
  - `argus_mcp/tui/screens/registry.py:208` -- inline `for name in ("config.yaml", "config.yml")`
  - `argus_mcp/tui/_dev_launch.py:48` -- inline `for name in ("config.yaml", "config.yml")`
- **Tool:** Grep (`grep -rn 'for.*config\.ya' argus_mcp/ --include='*.py'`)
- **Rule:** duplicate-logic
- **Description:** Six separate implementations search for `config.yaml`/`config.yml`. The canonical `find_config_file()` in `config/loader.py` checks CWD and package parent; `_find_config_path()` in setup_wizard checks only project root; the inline loops in tool_editor, skills, registry, and _dev_launch each check only CWD. The TUI screens do not reuse the canonical function.
- **Evidence:**
  ```python
  # config/loader.py (canonical)
  for name in _CONFIG_SEARCH_ORDER:
      candidate = os.path.join(base_dir, name)
      if os.path.isfile(candidate): return candidate

  # setup_wizard.py (separate)
  for name in ("config.yaml", "config.yml"):
      p = _PROJECT_ROOT / name
      if p.is_file(): return p

  # tool_editor.py, skills.py, registry.py (inline)
  for name in ("config.yaml", "config.yml"):
      p = Path.cwd() / name
      ...
  ```
- **Suggested fix:** Reuse `find_config_file()` from `config.loader` everywhere, or create a shared `config.discovery.find_config()` with configurable search dirs.

---

## Pattern 3: `getattr(obj, "attr", None)` Defensive Access

### [MEDIUM] Pervasive defensive attribute access (88+ occurrences)

- **Across:** 11+ files, 88+ total `getattr()` calls
- **Tool:** Grep (`grep -c 'getattr(' <files>`)
- **Rule:** code-smell
- **Counts by file:**
  | File | Count |
  |------|-------|
  | `server/lifespan.py` | 14 |
  | `tui/screens/settings.py` | 18 |
  | `cli.py` | 17 |
  | `server/handlers.py` | 8 |
  | `server/management/router.py` | 6 |
  | `tui/app.py` | 5 |
  | `tui/screens/health.py` | 5 |
  | `tui/screens/registry.py` | 5 |
  | `tui/screens/tool_editor.py` | 5 |
  | `tui/screens/skills.py` | 4 |
  | `config/diff.py` | 4 |
  | `tui/screens/tools.py` | 1 |
- **Description:** `getattr(obj, "attr", None)` is used extensively to access attributes that are monkey-patched or set dynamically on `app.state`, `mcp_server`, and `app` objects. This indicates a structural problem where proper typed interfaces are missing.
- **Evidence:**
  ```python
  getattr(app_s, "host", "N/A")           # lifespan.py
  getattr(mcp_server, "feature_flags", None)  # router.py
  getattr(service, "_config_path", None)      # lifespan.py
  getattr(app, "_last_status", None)          # tui screens
  getattr(mgr, "active_client", None)         # tui screens
  ```
- **Suggested fix:** Define typed dataclasses or TypedDicts for shared state:
  ```python
  @dataclass
  class AppState:
      host: str = "N/A"
      port: int = 0
      argus_service: Optional[ArgusService] = None
      ...
  ```

---

## Pattern 4: TUI Screen Config-File-Read-Modify-Write

### [MEDIUM] Repeated config YAML read-modify-write pattern across TUI screens

- **Files:**
  - `argus_mcp/tui/screens/skills.py:374-389` -- read config, modify backends dict, write back
  - `argus_mcp/tui/screens/tool_editor.py:256-270` -- read config, modify tools, write back
  - `argus_mcp/tui/screens/registry.py:220-233` -- read config, modify registries, write back
  - `argus_mcp/tui/screens/settings.py:571-591` -- read config, edit in TextArea, write back
- **Tool:** Grep (`grep -rn 'open.*config.*\.ya' argus_mcp/tui/`)
- **Rule:** duplicate-logic
- **Description:** Four TUI screens independently implement the same pattern: find config file, read YAML, modify a section, write YAML back. Each reimplements config path discovery, file I/O, error handling, and YAML round-tripping.
- **Evidence:**
  ```python
  # skills.py
  with open(config_path, "r", encoding="utf-8") as fh:
      cfg = yaml.safe_load(fh) or {}
  # ... modify cfg ...
  with open(config_path, "w", encoding="utf-8") as fh:
      yaml.safe_dump(cfg, fh, ...)

  # tool_editor.py -- identical structure
  # registry.py -- identical structure
  ```
- **Suggested fix:** Create a shared `ConfigEditor` utility:
  ```python
  class ConfigEditor:
      def __init__(self, path: Path): ...
      def read(self) -> dict: ...
      def write(self, data: dict) -> None: ...
      @contextmanager
      def modify(self):
          data = self.read()
          yield data
          self.write(data)
  ```

---

## Pattern 5: Theme Persistence

### [LOW] Repeated settings load/save for theme

- **File:** `argus_mcp/tui/app.py` (lines 878-882, 900-904, 909-927, 936-940)
- **Tool:** Grep (`grep -rn 'load_settings\|save_settings' argus_mcp/tui/app.py`)
- **Rule:** duplicate-logic
- **Description:** The pattern `settings = load_settings(); settings["theme"] = self.theme; save_settings(settings)` appears in 4 places: `action_quit`, `_shutdown_then_exit`, `action_next_theme`, and `action_open_theme_picker`. Each re-imports `load_settings` and `save_settings`.
- **Evidence:**
  ```python
  # Repeated 4 times:
  from argus_mcp.tui.settings import load_settings, save_settings
  settings = load_settings()
  settings["theme"] = self.theme
  save_settings(settings)
  ```
- **Suggested fix:** Extract `_save_theme_preference()`:
  ```python
  def _save_theme_preference(self):
      from argus_mcp.tui.settings import load_settings, save_settings
      settings = load_settings()
      settings["theme"] = self.theme
      save_settings(settings)
  ```

---

## Pattern 6: Dockerfile Generator Structural Duplication

### [MEDIUM] Three near-identical Dockerfile generation functions

- **File:** `argus_mcp/bridge/container/templates/_generators.py`
- **Functions:**
  - `generate_uvx_dockerfile()` (lines 273-324) -- 51 lines
  - `generate_npx_dockerfile()` (lines 327-377) -- 50 lines
  - `generate_go_dockerfile()` (lines 380-439) -- 59 lines
- **Tool:** Manual
- **Rule:** duplicate-logic
- **Description:** All three functions follow the same structure: resolve runtime config, select builder image, validate inputs, build `TemplateData`, render template. The shared steps are: `rc = runtime_config or RuntimeConfig.for_transport(...)`, `image = builder_image or rc.builder_image`, `package, validated_env, validated_deps = _validate_build_inputs(...)`, then constructing `TemplateData` with overlapping fields.
- **Evidence:**
  ```python
  # All three functions have this identical preamble:
  rc = runtime_config or RuntimeConfig.for_transport("uvx")  # or "npx" or "go"
  image = builder_image or rc.builder_image
  package, validated_env, validated_deps = _validate_build_inputs(package, build_env, system_deps)
  ```
- **Suggested fix:** Extract a common `_generate_dockerfile()` helper:
  ```python
  def _generate_dockerfile(transport: str, template: str, package: str, **kwargs) -> str:
      rc = kwargs.pop("runtime_config", None) or RuntimeConfig.for_transport(transport)
      image = kwargs.pop("builder_image", None) or rc.builder_image
      package, env, deps = _validate_build_inputs(package, kwargs.pop("build_env", None), ...)
      data = TemplateData(package=package, builder_image=image, build_env=env, system_deps=deps, **kwargs)
      return render_template(template, asdict(data))
  ```

---

## Pattern 7: TUI `query_one()` Widget Access

### [LOW] Massive `query_one()` usage across TUI (180+ occurrences)

- **Files:** All TUI screens and widgets
- **Tool:** Grep (`grep -c 'query_one' argus_mcp/tui/` = 180+)
- **Rule:** code-smell
- **Description:** 180+ `query_one()` calls across the TUI layer, each with a string ID or widget type. These are O(n) DOM lookups on every call. Many are repeated (e.g., the same widget is queried multiple times in the same method).
- **Top files by count:**
  | File | Count |
  |------|-------|
  | `tui/app.py` | 28 |
  | `tui/screens/settings.py` | 25 |
  | `tui/screens/setup_wizard.py` | 16 |
  | `tui/widgets/workflows_panel.py` | 8 |
  | `tui/screens/tool_editor.py` | 8 |
  | `tui/screens/skills.py` | 8 |
  | `tui/widgets/health_panel.py` | 7 |
  | `tui/widgets/capability_tables.py` | 6 |
- **Assessment:** This is a Textual framework pattern -- `query_one()` is the idiomatic way to access widgets. However, repeated lookups of the same widget within a single method could be cached in a local variable. Not a high priority.

---

## Pattern 8: Connection Status Notifications

### [LOW] Duplicated notification patterns

- **File:** `argus_mcp/tui/app.py`
- **Tool:** Manual
- **Rule:** duplicate-logic
- **Description:** Both `on_connection_lost` and `on_connection_restored` follow identical patterns: update ServerInfoWidget, add EventLogWidget entry, and (for lost) show notification. The structure is duplicated.
- **Suggested fix:** Extract a `_notify_connection_change(status, event_title, message)` method.

---

## Pattern 9: Backend Detail Construction

### [LOW] Repeated backend info building in two locations

- **Files:**
  - `argus_mcp/runtime/service.py` (in `get_status()`)
  - `argus_mcp/server/management/router.py:150-228` (in `handle_backends()`)
- **Tool:** Manual
- **Rule:** duplicate-logic
- **Description:** Both locations iterate `config_data` and check `active_sessions` to determine connection status, building similar backend info structures. `handle_backends()` augments with health data, groups, and status phases.
- **Suggested fix:** Centralize basic backend detail building in `ArgusService.get_backend_details()`.

---

## Pattern 10: Progress Callback Forwarding Chain

### [LOW] Progress callback pattern duplication across 3 layers

- **Files:** `runtime/service.py:329-343`, `bridge/client_manager.py:1158`, `display/installer.py:425`
- **Tool:** Manual
- **Rule:** duplicate-logic
- **Description:** Progress callbacks are wrapped, forwarded, and re-wrapped at three layers: service wraps to add events, passes to manager, which calls it during phase transitions. The callback signature and forwarding pattern is repeated.
- **Suggested fix:** Use an event-based observer pattern instead of callback chains.

---

## Summary

| Category | Count |
|----------|-------|
| Widget silencing pattern | 30 `except Exception` in app.py |
| Config discovery duplication | 6 implementations |
| Defensive getattr | 88+ instances across 11+ files |
| Config read-modify-write | 4 implementations in TUI screens |
| Theme persistence | 4 instances |
| Dockerfile generator duplication | 3 functions |
| TUI query_one repetition | 180+ instances |
| Connection notification | 2 instances |
| Backend detail building | 2 implementations |
| Progress callback chain | 3 layers |
| **Total duplicate patterns** | **10 patterns, 320+ instances** |
