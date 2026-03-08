# AI Coding Agent Smell Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI
**Methodology:** Pattern matching against AI coding agent mistake patterns from IEEE Spectrum, CodeRabbit, Endor Labs, Veracode, and CrowdStrike research (2025-2026)
**Auditor:** patterns-agent (code-quality-audit2 team)

---

## Detection Results: 13 of 15 Known AI Patterns Detected

### Pattern 1: Logic Errors That Look Correct -- DETECTED

- **Severity:** HIGH
- **Category:** logic-error
- **Description:** AI agents often produce code that runs without errors but doesn't do what it should.

**Evidence:**

- `argus_mcp/server/lifespan.py:153-273`: 13 attributes dynamically set on `mcp_svr_instance` (manager, registry, audit_logger, telemetry_enabled, middleware_chain, optimizer_enabled, optimizer_keep_list, optimizer_index, session_manager, feature_flags, version_checker, skill_manager, composite_tools). A typo like `mcp_svr_instance.optimzer_index` would silently create a new attribute with no error.
- `argus_mcp/server/lifespan.py:608`: `if "_exit_stack" in dir() and _exit_stack is not None:` checks for a variable name as a string. If the variable is renamed, cleanup is silently skipped.
- `argus_mcp/server/handlers.py:202`: `except Exception: pass` in handler dispatch -- errors in resource/prompt reading silently return empty results.

### Pattern 2: Missing Input Validation -- DETECTED

- **Severity:** CRITICAL
- **Category:** input-validation
- **Description:** The #1 AI code flaw per research. AI-generated code often skips input validation at system boundaries.

**Evidence:**

- `argus_mcp/server/management/router.py:468-471`: `timeout_seconds` from HTTP request body now validates `ValueError`/`TypeError` (improved), but still lacks bounds validation. A client could set `timeout=999999` (nearly infinite) or `timeout=0` (immediate forced shutdown).
- `argus_mcp/server/management/router.py:374`: `limit = int(request.query_params.get("limit", "100"))` -- no bounds check; a client could request `limit=99999999` causing memory exhaustion on the event list.
- `argus_mcp/tui/screens/setup_wizard.py:142`: User YAML parsed without size limits or depth restrictions via `yaml.safe_load()`.
- **Suggested fix:** Add bounds: `timeout = max(1, min(timeout, 300))` and `limit = max(1, min(limit, 1000))`.

### Pattern 3: Swallowed Exceptions -- DETECTED

- **Severity:** HIGH
- **Category:** swallowed-exceptions
- **Description:** AI agents frequently add `except Exception: pass` to prevent crashes.

**Evidence:** 264 broad `except Exception` clauses across the codebase. The TUI alone has 100+ instances. The top files: `tui/app.py` (30), `bridge/client_manager.py` (19), `tui/screens/setup_wizard.py` (17). This is the classic AI pattern of "make the code not crash" rather than "handle errors correctly."

**Partial mitigation:** Several previously-silent handlers now log at debug level. See `error-handling.md` for full analysis.

### Pattern 4: Inconsistent Error Handling -- DETECTED

- **Severity:** MEDIUM
- **Category:** inconsistency
- **Description:** Different patterns for the same kind of error across files.

**Evidence:**

| Scenario | File A | File B |
|----------|--------|--------|
| Config load failure | `cli.py:505` -- debug log, use defaults | `runtime/service.py:306` -- raises `ConfigurationError` |
| Container error | `container/runtime.py` -- `except: pass` | `container/wrapper.py` -- raises with message |
| Settings I/O | `tui/settings.py:80` -- `except Exception: pass` | `bridge/auth/store.py:83` -- `except OSError as exc: log` |

### Pattern 5: Over-Engineering -- DETECTED

- **Severity:** MEDIUM
- **Category:** over-engineering
- **Description:** AI tends to create unnecessary abstractions, factories, and middleware chains.

**Evidence:**

- Middleware chain (`bridge/middleware/`) creates an elaborate `MCPHandler`/`MCPMiddleware` protocol with `build_chain()` factory, but only ever has 3-4 middlewares.
- `SecretProvider` hierarchy uses a factory pattern for 3 providers that could be a simple if/elif.
- `ServiceState` enum with `is_valid_transition()` implements a 7-state machine, but transitions are only checked in 2 places.
- `CapabilityRegistry` (423 lines) provides rename, filter, and conflict resolution features that appear underutilized.

### Pattern 6: Dead Code / Unused Imports -- DETECTED

- **Severity:** LOW
- **Category:** dead-code
- **Description:** AI generates imports "just in case" and leaves dead branches.

**Evidence:**
- `_PANEL_IMPORTS_DONE` guard in `settings.py` with empty body
- `_type_priority` dict recreated on every `start_all()` call
- See `dead-code.md` and `static-analysis.md` for full analysis.

### Pattern 7: Blocking Calls in Async -- DETECTED (IMPROVED)

- **Severity:** MEDIUM (was HIGH)
- **Category:** blocking-async
- **Description:** AI agents frequently call synchronous I/O functions from async code.

**Evidence:** 2 confirmed remaining instances of blocking I/O in async functions (was 8). Key fixes:
- `runtime/service.py:582`: Config hash now uses `asyncio.to_thread()` (FIXED)
- `bridge/auth/store.py:76,101`: Token I/O now uses `asyncio.to_thread()` (FIXED)
- `container/image_builder.py:404`: Dockerfile write now uses `asyncio.to_thread()` (FIXED)

**Remaining:** `open(os.devnull)` in `client_manager.py:355`, `_read_config_file()` in `config/loader.py:70-71`. See `async-antipatterns.md` for details.

### Pattern 8: Race Conditions -- DETECTED (IMPROVED)

- **Severity:** MEDIUM (was MEDIUM)
- **Category:** race-condition
- **Description:** Shared mutable state accessed from multiple async tasks without locks.

**Evidence:**
- TUI `_connected`/`_caps_loaded` flags modified from worker threads (mitigated by Textual message queue)
- `_devnull` lazy initialization in concurrent context (mitigated by semaphore)

**Fixed:**
- `_event_id_counter` in `ArgusService` replaced with `uuid.uuid4()` -- race condition eliminated
- `_argus_bg_tasks` event loop injection replaced with module-level `_background_tasks` set

### Pattern 9: Resource Leaks -- DETECTED (IMPROVED)

- **Severity:** MEDIUM (was HIGH)
- **Category:** resource-leak
- **Description:** Files, sockets, subprocesses not properly closed in error paths.

**Evidence:**
- `bridge/client_manager.py:355`: `open(os.devnull, "w")` stored as `self._devnull`. Now uses a single shared handle per ClientManager instance (was one per backend). Closed in `stop_all()`.
- `cli.py:230-236`: `out_fd = open(out_path, "a")` used with `Popen` -- `out_fd.close()` called on line 236 after Popen creation. If Popen raises, the fd leaks. Should use context manager.

### Pattern 10: Hardcoded Values -- DETECTED

- **Severity:** MEDIUM
- **Category:** magic-numbers
- **Description:** Magic numbers, hardcoded paths, embedded configuration.

**Evidence:** 20+ hardcoded timeouts scattered across the codebase: 3.0s, 5.0s, 10.0s, 15.0s, 30.0s, 60.0s, 120.0s, 600.0s. Many are in `constants.py` (good), but several remain inline:
- `lifespan.py:610`: `timeout=10.0` for session manager shutdown
- `pkce.py:398`: `timeout=30.0` for HTTP client
- `management/router.py:492`: `asyncio.sleep(0.5)` for deferred shutdown
- `management/router.py:468`: `timeout = 30` default

### Pattern 11: Copy-Paste Code -- DETECTED

- **Severity:** MEDIUM
- **Category:** copy-paste
- **Description:** Near-identical blocks repeated instead of being abstracted.

**Evidence:**
- 100+ identical `try: widget.query_one(...) except Exception: pass` blocks in TUI
- 3 config search implementations (cli.py, setup_wizard.py, _cmd_tui)
- Container runtime operations (image_exists, build_image, etc.) have near-identical try/except patterns in `runtime.py`
- See `duplicate-logic.md` for full analysis.

### Pattern 12: Missing Type Narrowing -- DETECTED

- **Severity:** MEDIUM
- **Category:** type-safety
- **Description:** Using `Any` or `Optional` without narrowing, leading to potential None dereference.

**Evidence:**
- `mcp_svr_instance: Any` in lifespan functions -- no type checking on 13 attribute assignments
- `self._server_manager: Optional[object]` in TUI -- loses all type info
- 30+ `getattr(obj, "attr", None)` defensive accesses indicating missing type guarantees (e.g., `server/management/router.py:503`, `server/lifespan.py:157`)

### Pattern 13: Monkey-Patching -- DETECTED (IMPROVED)

- **Severity:** HIGH (was CRITICAL)
- **Category:** monkey-patching
- **Description:** Setting attributes on objects dynamically, bypassing type system.

**Evidence:**
- 13 attributes dynamically set on `mcp_server` in `lifespan.py:153-273` (manager, registry, audit_logger, telemetry_enabled, middleware_chain, optimizer_enabled, optimizer_keep_list, optimizer_index, session_manager, feature_flags, version_checker, skill_manager, composite_tools)
- `app_s.argus_service = service` dynamic attribute on Starlette state (acceptable Starlette pattern)

**Fixed:**
- `loop._argus_bg_tasks` event loop monkey-patching eliminated -- replaced with module-level `_background_tasks: set` in `router.py:47`
- **Suggested fix:** Introduce a `ServerContext` dataclass or typed namespace to replace the 13 monkey-patched attributes on `mcp_server`.

### Pattern 14: God Objects -- DETECTED

- **Severity:** MEDIUM
- **Category:** god-object
- **Description:** Classes/functions doing too many things.

**Evidence:**
- `ClientManager`: 1,757 lines, highest complexity in `start_all()` spanning 250+ lines
- `ArgusApp`: 958 lines, 30+ methods
- `ArgusService`: 849 lines, 15+ methods
- `SetupWizard`: 746 lines
- `ContainerRuntime` hierarchy: 742 lines total across multiple classes

### Pattern 15: Inconsistent Naming -- DETECTED

- **Severity:** LOW
- **Category:** naming
- **Description:** Different names for the same concept across files.

**Evidence:**
- `svr_name` vs `server_name` vs `backend_name` vs `name` for the same concept (backend identifier)
- `e_cfg`, `e_backend`, `e_exc`, `e_fatal`, `e_bind`, `e_serve`, `e_log_cfg` Hungarian-style exception naming in `cli.py`
- `_argus_cfg` vs `full_cfg` vs `config` for configuration objects
- See `naming-and-conventions.md` for details.

---

## Patterns NOT Detected (2)

- **Forgotten await:** No instances of un-awaited coroutines found. All `async def` functions are properly awaited or wrapped in `create_task()`.
- **Fake output matching expected format:** No instances of stub/mock data returned as real data.

---

## Assessment Summary

**13 of 15 AI coding agent mistake patterns detected.** Improvements since previous audit:

| Area | Previous | Current | Change |
|------|----------|---------|--------|
| Fire-and-forget tasks | 7 unhandled | 1 unhandled | -86% |
| Blocking I/O in async | 8 instances | 2 remaining | -75% |
| Event loop monkey-patching | Yes | Eliminated | FIXED |
| Event ID race condition | Counter without lock | uuid4() | FIXED |
| Token store I/O | Sync in async | asyncio.to_thread() | FIXED |
| Shutdown validation | Silent pass | Returns 400 | FIXED |

**Most concerning remaining issues:**

1. **13 monkey-patched attributes on mcp_server** (Pattern 13) -- architecturally risky, creates fragile implicit coupling
2. **264 broad except clauses** (Pattern 3) -- the "make it not crash" anti-pattern at epidemic scale
3. **Missing input validation at HTTP boundaries** (Pattern 2) -- no bounds on timeout/limit parameters
4. **God objects** (Pattern 14) -- ClientManager at 1,757 lines
5. **100+ copy-paste TUI exception blocks** (Pattern 11) -- no safe_query() utility yet

---

## Recommendations

1. **Introduce a `ServerContext` dataclass** to replace all 13 monkey-patched attributes on `mcp_server`
2. **Add a TUI `safe_query()` utility** to replace 100+ identical try/except blocks
3. **Wrap remaining file I/O in async** using `asyncio.to_thread()` (config/loader.py, client_manager devnull)
4. **Add bounds validation** on all HTTP request parameters (timeout, limit)
5. **Add `_log_task_exception` callback** to `tui/screens/registry.py:64`
6. **Decompose `ClientManager`** into focused classes (coordinator, transport factory, retry manager)
7. **Standardize naming** on `backend_name` for backend identifiers
