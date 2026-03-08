# Performance Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI (159+ files, ~29K lines)
**Tools:** Radon CC (v6.0.1), Grep pattern analysis, Manual inspection

---

## Blocking I/O in Async Context

### [HIGH] Synchronous YAML load in async context

- **File:** `argus_mcp/config/loader.py:70-71`
- **Tool:** Manual
- **Rule:** blocking-io-in-async
- **Description:** `_read_config_file()` performs synchronous YAML parsing via `yaml.safe_load(f)`. When called from async functions (e.g., `service.start()` or `service.reload()`), this blocks the event loop. The function is purely synchronous and is not wrapped with `asyncio.to_thread()` at either the definition or call site.
- **Evidence:**
  ```python
  with open(cfg_fpath, "r", encoding="utf-8") as f:
      raw_data = yaml.safe_load(f)
  ```
- **Suggested fix:** Wrap in `asyncio.to_thread()` at the call site, or provide an async variant.

### [MEDIUM] Synchronous JSON file I/O in async-adjacent code

- **File:** `argus_mcp/skills/manager.py:221-222,230-231`
- **Tool:** Manual
- **Rule:** blocking-io-in-async
- **Description:** `_load_state()` and `_save_state()` read/write JSON files synchronously. Called from `discover()` which is invoked from `_attach_to_mcp_server()` (async context via lifespan).
- **Evidence:**
  ```python
  with open(self._state_file, "r", encoding="utf-8") as f:
      return json.load(f)
  ```
- **Suggested fix:** Wrap calls in `asyncio.to_thread()`.

### [MEDIUM] Synchronous file I/O in TUI workflow panel

- **File:** `argus_mcp/tui/widgets/workflows_panel.py:75,353`
- **Tool:** Manual
- **Rule:** blocking-io-in-async
- **Description:** `fpath.read_text()`, `yaml.safe_load()`, and `dest.write_text()` in synchronous methods called from a Textual screen. While Textual workers mitigate some event loop blocking, these calls are still on the main thread during compose and action handlers.
- **Suggested fix:** Use Textual `run_worker()` for file I/O operations.

### [LOW] Synchronous settings file I/O in TUI

- **File:** `argus_mcp/tui/settings.py:72-73,89-90`
- **Tool:** Manual
- **Rule:** blocking-io-in-async
- **Description:** `load_settings()` and `save_settings()` use synchronous `open()` / `json.load()` / `json.dump()`. Called frequently from TUI event handlers (theme changes, server management).
- **Evidence:**
  ```python
  with open(_SETTINGS_FILE, encoding="utf-8") as fh:
      data = json.load(fh)
  ```
- **Suggested fix:** Wrap in `asyncio.to_thread()` or cache settings in memory.

### [LOW] Synchronous server manager config I/O

- **File:** `argus_mcp/tui/server_manager.py:224-225,271-272`
- **Tool:** Manual
- **Rule:** blocking-io-in-async
- **Description:** `load()` and `save()` use synchronous `open()` / `json.load()`. Called from TUI event handlers.
- **Evidence:**
  ```python
  with open(self._config_path, encoding="utf-8") as fh:
      data: Dict[str, Any] = json.load(fh)
  ```

### Notable Fixes Since Previous Audit

- `argus_mcp/runtime/service.py:582` -- **FIXED** -- Now uses `asyncio.to_thread(Path(...).read_bytes)` for config hash computation.
- `argus_mcp/bridge/auth/store.py:76,101` -- **FIXED** -- Now uses `asyncio.to_thread(path.write_text, ...)` and `asyncio.to_thread(path.read_text, ...)`.
- `argus_mcp/bridge/container/image_builder.py:399-404` -- **FIXED** -- Dockerfile write wrapped in `asyncio.to_thread(_write_dockerfile, ...)`.

---

## Radon Complexity Hotspots

### [HIGH] _discover_caps_by_type() -- CC=29, Grade D

- **File:** `argus_mcp/bridge/capability_registry.py:59`
- **Tool:** Radon CC
- **Rule:** CC=29
- **Description:** The most complex function in the current codebase. Discovery with filtering, renaming, conflict resolution, and timeout handling. Its high complexity makes the capability registration path difficult to optimize or debug.

### [HIGH] InstallerDisplay.update() -- CC=25, Grade D

- **File:** `argus_mcp/display/installer.py:425`
- **Tool:** Radon CC
- **Rule:** CC=25
- **Description:** Phase-specific display updates. Called on every progress callback during startup. High CC means many branches on every call.

### [HIGH] ToolsScreen.on_input_changed() -- CC=23, Grade D

- **File:** `argus_mcp/tui/screens/tools.py:114`
- **Tool:** Radon CC
- **Rule:** CC=23
- **Description:** Fires on every keystroke in the search input. Multi-field matching with 23 branch points per invocation.
- **Suggested fix:** Debounce input and extract filtering to a pure function.

### [HIGH] app_lifespan() -- CC=22, Grade D

- **File:** `argus_mcp/server/lifespan.py:412`
- **Tool:** Radon CC
- **Rule:** CC=22
- **Description:** Server startup and shutdown logic with multiple exception handlers. Performance impact is low (runs once) but high complexity makes startup debugging difficult.

### [HIGH] _cmd_stop() -- CC=22, Grade D

- **File:** `argus_mcp/cli.py:343`
- **Tool:** Radon CC
- **Rule:** CC=22

### [HIGH] ArgusService._build_registry() -- CC=22, Grade D

- **File:** `argus_mcp/runtime/service.py:178`
- **Tool:** Radon CC
- **Rule:** CC=22

### [HIGH] SkillsScreen.action_apply_skill() -- CC=20, Grade D

- **File:** `argus_mcp/tui/screens/skills.py:326`
- **Tool:** Radon CC
- **Rule:** CC=20

---

## Unnecessary Copies

### [LOW] List copies in property accessors

- **File:** `argus_mcp/runtime/service.py:139,143,147`
- **Tool:** Manual
- **Rule:** unnecessary-copy
- **Description:** Properties `tools`, `resources`, and `prompts` create new `list()` copies on every access. These are called from `handle_backends()` (3x per call) and `handle_capabilities()`, creating 6+ list copies per API request.
- **Evidence:**
  ```python
  @property
  def tools(self) -> List[mcp_types.Tool]:
      return list(self._tools)
  ```
- **Suggested fix:** Return `tuple()` or use `@functools.cached_property` with invalidation.

### [LOW] Dict copies in capability registry properties

- **File:** `argus_mcp/bridge/capability_registry.py:333,337,341,345`
- **Tool:** Manual
- **Rule:** unnecessary-copy
- **Description:** Properties `tools`, `resources`, `prompts`, and `route_map` each call `.copy()` on every access.
- **Evidence:**
  ```python
  return self._tools.copy()
  return self._resources.copy()
  return self._prompts.copy()
  return self._route_map.copy()
  ```
- **Suggested fix:** Return frozen views or cache copies with invalidation on mutation.

### [LOW] Event deque converted to list for every query

- **File:** `argus_mcp/runtime/service.py:814`
- **Tool:** Manual
- **Rule:** unnecessary-copy
- **Description:** `list(self._events)` creates a full copy on every `get_events()` call, then filters and slices. Two additional list comprehensions follow.
- **Evidence:**
  ```python
  result = list(self._events)
  if since:
      result = [e for e in result if e["timestamp"] > since]
  if severity:
      result = [e for e in result if e["severity"] == severity]
  return result[-limit:]
  ```
- **Suggested fix:** Use a single list comprehension with combined filtering.

### [LOW] List copies during iteration for mutation safety

- **File:** `argus_mcp/bridge/client_manager.py:277,1253`
- **File:** `argus_mcp/tui/server_manager.py:188,199`
- **Tool:** Manual
- **Rule:** unnecessary-copy
- **Description:** `list(self._pending_tasks.values())` and `list(self._backend_stacks.items())` create copies for safe iteration during mutation. This is correct but could be avoided with structural changes.

---

## Polling Inefficiency

### [MEDIUM] TUI polls full status on every tick

- **File:** `argus_mcp/tui/app.py:473-532`
- **Tool:** Manual
- **Rule:** polling-overhead
- **Description:** `_poll_once()` fetches status, backends, capabilities, and events every 2 seconds. Each poll cycle makes 2-4 HTTP requests. With multiple TUI clients, this multiplies server load.
- **Evidence:** The method sequentially awaits `get_status()`, `get_capabilities()` (on first connect), `get_events()`, and `get_backends()`.
- **Suggested fix:** Use SSE event stream for push-based updates instead of polling.

---

## Sleep/Delay Patterns

### [LOW] Multiple sleep-based coordination patterns

- **File:** `argus_mcp/bridge/client_manager.py:390,903,1095,1112`
- **Tool:** Grep
- **Rule:** sleep-coordination
- **Description:** Several `asyncio.sleep()` calls are used for coordination:
  - Line 390: SSE startup delay (`await asyncio.sleep(sse_startup_delay)`)
  - Line 903: Stagger delay between concurrent launches
  - Line 1095: Exponential backoff retry delay
  - Line 1112: Stagger delay in retry loop
- **Assessment:** The stagger and backoff patterns are appropriate for their use case. The SSE startup delay is a fixed wait that could be replaced with readiness probing.

### [LOW] Busy-wait in workflow execution

- **File:** `argus_mcp/tui/widgets/workflows_panel.py:433`
- **Tool:** Grep
- **Rule:** busy-wait
- **Description:** `await asyncio.sleep(0.1)` in a loop waiting for workflow step completion.
- **Suggested fix:** Use an `asyncio.Event` for step completion signaling.

### [LOW] Sleep before shutdown

- **File:** `argus_mcp/server/management/router.py:492`
- **Tool:** Grep
- **Rule:** gratuitous-sleep
- **Description:** `await asyncio.sleep(0.5)` to "allow response to flush" before triggering shutdown.
- **Suggested fix:** Use proper response completion callbacks.

---

## Startup Performance

### [MEDIUM] Sequential stdio image builds

- **File:** `argus_mcp/bridge/client_manager.py:1190`
- **Tool:** Manual
- **Rule:** startup-latency
- **Description:** `_build_and_connect_stdio()` builds all stdio backend images sequentially. While remote backends are launched concurrently in parallel (via `_launch_remote_backends()`), stdio backends cannot overlap their Docker builds.
- **Evidence:**
  ```python
  remote_tasks = self._launch_remote_backends(remote_items, sem, stagger, concurrency)
  if remote_tasks:
      await asyncio.sleep(0)
  stdio_results = await self._build_and_connect_stdio(stdio_items)
  ```
- **Assessment:** Remote backends now launch immediately (improvement from previous audit). Stdio sequential builds are by design to avoid Docker build cache contention. The `asyncio.sleep(0)` ensures remote tasks get scheduled before blocking on stdio builds.

---

## Summary

| Category | Count |
|----------|-------|
| Blocking I/O in async | 5 (3 fixed from previous audit) |
| Complexity hotspots (CC >= 20) | 8 |
| Unnecessary copies | 4 patterns |
| Polling inefficiency | 1 |
| Sleep/delay patterns | 3 |
| Startup latency | 1 |
| **Total performance findings** | **22** |
