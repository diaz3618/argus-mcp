# Async Anti-Patterns Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI
**Focus:** Python asyncio-specific issues per Python docs and SuperFastPython guidelines
**Auditor:** patterns-agent (code-quality-audit2 team)

---

## 1. Fire-and-Forget Tasks -- Exception Handling Audit (12 locations)

`asyncio.create_task()` is called in 12 locations. The codebase now includes a shared `_log_task_exception` utility (`argus_mcp/_task_utils.py`) that logs unhandled exceptions from background tasks. This is a significant improvement.

| # | File:Line | Task Name | Exception Handling | Severity |
|---|-----------|-----------|-------------------|----------|
| 1 | `config/watcher.py:68` | `config-watcher` | `_log_task_exception` callback | RESOLVED |
| 2 | `server/management/router.py:479` | `management_shutdown` | `_log_task_exception` + `_background_tasks` set | RESOLVED |
| 3 | `server/session/manager.py:46` | `session-cleanup` | `_log_task_exception` callback | RESOLVED |
| 4 | `bridge/health/checker.py:122` | `health-checker` | `_log_task_exception` callback | RESOLVED |
| 5 | `bridge/health/checker.py:303` | unnamed health check | `_log_task_exception` + `_background_tasks` set | RESOLVED |
| 6 | `bridge/client_manager.py:117` | stdout log task | `_log_task_exception` callback | RESOLVED |
| 7 | `bridge/client_manager.py:123` | stderr log task | `_log_task_exception` callback | RESOLVED |
| 8 | `bridge/client_manager.py:906` | remote start task | Awaited via gather (return_exceptions=True) | LOW |
| 9 | `bridge/client_manager.py:946` | stdio build task | Awaited directly with try/except | LOW |
| 10 | `bridge/client_manager.py:1115` | retry task | Awaited via gather (return_exceptions=True) | LOW |
| 11 | `bridge/client_manager.py:1453` | auth discovery | `_log_task_exception` callback | RESOLVED |
| 12 | `tui/screens/registry.py:64` | `_load_task` | **No callback** | MEDIUM |

### [MEDIUM] Registry load task lacks exception callback

- **File:** `argus_mcp/tui/screens/registry.py:64`
- **Category:** fire-and-forget
- **Description:** `asyncio.create_task(self._load_registry())` has no `_log_task_exception` callback. If the registry fetch fails with an unexpected exception (e.g., DNS resolution error), the task silently dies.
- **Evidence:**
  ```python
  self._load_task: asyncio.Task[None] | None = asyncio.create_task(self._load_registry())
  ```
- **Suggested fix:** Add `self._load_task.add_done_callback(_log_task_exception)`

### Improvement Summary

The `_task_utils._log_task_exception` pattern is now applied to 8 of 12 create_task locations. 3 more are properly awaited via gather or direct await. Only 1 location (registry.py) lacks exception handling.

---

## 2. Blocking Calls in Async Context

### [HIGH] Synchronous file open in async backend init

- **File:** `argus_mcp/bridge/client_manager.py:355`
- **Category:** blocking-io-in-async
- **Description:** `open(os.devnull, "w")` in an async function (`_init_stdio_backend`). This is a blocking system call. While opening `/dev/null` is fast, the pattern is incorrect.
- **Evidence:**
  ```python
  if self._devnull is None:
      self._devnull = open(os.devnull, "w")  # noqa: SIM115
  ```
- **Suggested fix:** Open during `__init__` (sync) or use `asyncio.to_thread()`.

### [MEDIUM] Synchronous YAML load called from async

- **File:** `argus_mcp/config/loader.py:70-71`
- **Category:** blocking-io-in-async
- **Description:** `open()` and `yaml.safe_load()` in `_read_config_file()`, which is called from async `service.start()` and `service.reload()`. This blocks the event loop during config reads.
- **Evidence:**
  ```python
  with open(cfg_fpath, "r", encoding="utf-8") as f:
      raw_data = yaml.safe_load(f)
  ```
- **Suggested fix:** Wrap `_read_config_file()` call in `asyncio.to_thread()`.

### [MEDIUM] Synchronous JSON file I/O in skills manager

- **File:** `argus_mcp/skills/manager.py:221-222`
- **Category:** blocking-io-in-async
- **Description:** `open()` + `json.load()` for skill state persistence. Called from sync context (`_load_state` is sync), but `_save_state` (line 226) also uses sync `open()` and could be called during async operations.
- **Evidence:**
  ```python
  with open(self._state_file, "r", encoding="utf-8") as f:
      return json.load(f)
  ```

### [LOW] Synchronous workflow YAML scanning

- **File:** `argus_mcp/server/lifespan.py:86`
- **Category:** blocking-io-in-async
- **Description:** `fpath.read_text()` and `yaml.safe_load()` during lifespan startup. Acceptable because it runs during the startup phase before the server accepts requests.

### [LOW] Synchronous TUI settings I/O

- **File:** `argus_mcp/tui/settings.py:72,89`
- **Category:** blocking-io-in-async
- **Description:** `json.load()` and `json.dump()` in TUI settings. These are called from synchronous functions (`load_settings`, `save_settings`), so they are not blocking an async event loop directly. TUI calls these from workers.

### Resolved Since Previous Audit

| Item | File | Previous | Current | Status |
|------|------|----------|---------|--------|
| Config hash in watcher | `runtime/service.py:582` | Sync `open()` + `fh.read()` | `asyncio.to_thread(Path.read_bytes)` | FIXED |
| Dockerfile write | `container/image_builder.py:399` | Sync `open()` in async | `asyncio.to_thread(_write_dockerfile, ...)` | FIXED |
| Token persistence | `bridge/auth/store.py:76,101` | Sync `write_text()`/`read_text()` | `asyncio.to_thread(path.write_text, ...)` / `asyncio.to_thread(path.read_text, ...)` | FIXED |

**Remaining count:** 2 HIGH/MEDIUM blocking I/O issues, 2 LOW (acceptable).

---

## 3. Missing Cancellation Handling

### [MEDIUM] PKCE flow lacks cancellation support

- **File:** `argus_mcp/bridge/auth/pkce.py:259`
- **Category:** missing-cancellation
- **Description:** The PKCE OAuth flow blocks for user interaction (up to 10 minutes waiting for browser callback). It only has a timeout, no cancellation support. If the user cancels startup via Ctrl+C, this flow cannot be interrupted cleanly.
- **Suggested fix:** Accept a `cancellation_event: asyncio.Event` parameter and check it periodically.

### [MEDIUM] Image builder lacks cancellation

- **File:** `argus_mcp/bridge/container/image_builder.py:87`
- **Category:** missing-cancellation
- **Description:** Docker image builds can take minutes. The `ensure_image()` function has no way to cancel a build in progress. The `cancel_startup()` mechanism in `ClientManager` only cancels pending tasks, not running subprocess builds.

---

## 4. Race Conditions with Shared State

### [MEDIUM] TUI connection state flags

- **File:** `argus_mcp/tui/app.py`
- **Category:** race-condition
- **Description:** `self._connected` and `self._caps_loaded` modified by worker threads. Mitigated by Textual's message queue serialization, but the pattern is fragile if workers are used outside the message system.

### [LOW] `_devnull` lazy initialization

- **File:** `argus_mcp/bridge/client_manager.py:354-355`
- **Category:** race-condition
- **Description:** `self._devnull` is lazily initialized in `_init_stdio_backend()`. Multiple concurrent calls could theoretically create multiple devnull handles. In practice, the semaphore and sequential stdio processing prevent this, but the pattern is a code smell.
- **Suggested fix:** Initialize in `__init__`.

### Resolved Since Previous Audit

| Item | Previous | Current | Status |
|------|----------|---------|--------|
| `_event_id_counter` without lock | Incrementing counter | `uuid.uuid4().hex[:12]` | FIXED |
| Event loop `_argus_bg_tasks` injection | `loop._argus_bg_tasks = set()` | Module-level `_background_tasks: set` | FIXED |

---

## 5. Async Synchronization Audit

The codebase uses the following synchronization primitives:

| File | Primitive | Purpose | Assessment |
|------|-----------|---------|------------|
| `config/watcher.py:58` | `asyncio.Event` | Stop signal for watcher | Correct |
| `bridge/health/checker.py:112` | `asyncio.Event` | Stop signal for checker | Correct |
| `bridge/auth/provider.py:89,183` | `asyncio.Lock` | Token refresh serialization | Correct |
| `bridge/auth/pkce.py:116,274` | `asyncio.Event` | PKCE callback readiness | Correct |
| `bridge/client_manager.py:883,1044,1178` | `asyncio.Semaphore` | Startup concurrency limit | Correct |
| `runtime/service.py:87` | `asyncio.Event` | Service readiness | Correct |
| `runtime/service.py:90` | `asyncio.Lock` | Reload serialization | Correct |

**Assessment:** Synchronization usage is correct. The reload lock prevents concurrent reload operations. The semaphore limits concurrent backend connections. The auth lock prevents concurrent token refreshes.

**Missing:** No lock protects the event subscriber list in `ArgusService` (`_event_subscribers` accessed from multiple async tasks).

---

## 6. `_task_utils.py` -- Shared Utility (NEW)

- **File:** `argus_mcp/_task_utils.py`
- **Description:** New shared utility providing `_log_task_exception` done-callback for background tasks. This addresses the fire-and-forget anti-pattern systematically.
- **Assessment:** Well-implemented. Checks for cancellation before logging. Uses `exc_info=exc` for full traceback.
- **Coverage:** Used in 6 files (client_manager, config/watcher, server/session/manager, server/management/router, bridge/health/checker).

---

## Summary

| Anti-Pattern | Count | Severity |
|-------------|-------|----------|
| Fire-and-forget tasks without exception handling | 1 of 12 tasks (was 7) | MEDIUM |
| Blocking I/O in async | 2 remaining (was 8) | HIGH/MEDIUM |
| Missing cancellation handling | 2 long-running operations | MEDIUM |
| Race conditions (potential) | 2 patterns (was 3+1) | MEDIUM/LOW |
| **Total distinct issues** | **7** (was 22) | |

### Delta from Previous Audit

- **Fire-and-forget tasks:** 7 unhandled -> 1 unhandled (86% reduction)
- **Blocking I/O:** 8 instances -> 2 remaining (75% reduction)
- **Event loop monkey-patching:** ELIMINATED (module-level set)
- **Race conditions:** 2 fixed (event counter, loop injection)
- **New utility:** `_task_utils.py` provides systematic solution
