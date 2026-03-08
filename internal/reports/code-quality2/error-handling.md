# Error Handling Audit

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI
**Tools:** grep, manual code inspection
**Auditor:** patterns-agent (code-quality-audit2 team)

---

## Overview

- **Total broad `except Exception` clauses:** 264 across the codebase
- **Files with highest concentration:** `tui/app.py` (30), `bridge/client_manager.py` (19), `tui/screens/setup_wizard.py` (17), `tui/screens/settings.py` (15), `tui/widgets/workflows_panel.py` (11), `tui/screens/skills.py` (11), `cli.py` (11), `bridge/container/runtime.py` (11)
- **Bare `except:` clauses:** 0 (good -- none found)
- **No `except ... pass` with Bandit B110 literal match** (handlers now use logging or meaningful fallbacks in most cases)

### Changes Since Previous Audit

Several improvements observed:
- `cli.py:89-93`: Transport type detection failure now logs at debug level with `exc_info=True` (was silent)
- `cli.py:505-506`: Client config load failure now logs at debug level (was silent `pass`)
- `server/management/router.py:472-475`: Shutdown body parse now returns 400 for `ValueError`/`TypeError` (was silent)
- `secrets/resolver.py`, `bridge/auth/store.py`: Token I/O now uses `asyncio.to_thread()` with `OSError`-specific catches

---

## Category 1: TUI Widget Access -- `except Exception:` (100+ instances)

These are the most numerous. The pattern silences all exceptions when querying Textual widgets that may not be mounted.

### [LOW] tui/app.py -- 30 instances

- **File:** `argus_mcp/tui/app.py:283,301,408,490,518,548,558,567,583,592,618,653,668,707,716,742,751,765,774,816,830,840,850,861,870` (and more)
- **Category:** try_except_pass
- **Description:** Widget query + update wrapped in `try/except Exception: pass`. While these are low-severity individually (widgets genuinely may not be mounted), the pattern masks real bugs like incorrect widget IDs, type errors, or attribute errors.
- **Evidence:**
  ```python
  except Exception:
      pass  # Widget not in active screen
  ```
- **Suggested fix:** Catch `textual.css.query.NoMatches` specifically, or use a `safe_query()` helper:
  ```python
  from textual.css.query import NoMatches
  try: ... except NoMatches: pass
  ```

### [LOW] tui/screens/setup_wizard.py -- 17 instances

- **File:** `argus_mcp/tui/screens/setup_wizard.py:242,248,254,283,306,338,362,383,504,511,555,564,571,632,655,667`
- **Category:** try_except_pass
- **Description:** Widget updates and validation wrapped in broad exception handling. Mix of appropriately-logged (e.g., line 283 logs `exc_info`) and silently swallowed.

### [LOW] tui/screens/settings.py -- 15 instances

- **File:** `argus_mcp/tui/screens/settings.py:294,313,376,417,517,539,546,585,602,634,644,673,680` (and more)
- **Category:** try_except_pass

### [LOW] tui/screens/skills.py -- 11 instances

- **File:** `argus_mcp/tui/screens/skills.py:165,218,222,247,456`
- **Category:** try_except_pass

### [LOW] tui/widgets/ -- 40+ instances across panels

- **Files:** `workflows_panel.py` (11), `optimizer_panel.py` (6), `otel_panel.py` (5), `health_panel.py` (4), `sessions_panel.py` (3), `secrets_panel.py` (3), `sync_status.py` (3), `backend_status.py` (2), `version_drift.py` (2), `server_groups.py` (2), `network_panel.py` (2), `middleware_panel.py` (2), `registry_browser.py` (2), `filter_toggle.py` (1), `install_panel.py` (1), `param_editor.py` (1), `event_log.py` (2), `server_info.py` (1), `capability_tables.py` (1)
- **Category:** try_except_pass

### [LOW] tui/screens/ -- additional instances

- **Files:** `tools.py` (5), `health.py` (6), `registry.py` (6), `tool_editor.py` (4), `client_config.py` (4), `audit_log.py` (6), `security.py` (3), `exit_modal.py` (1), `server_detail.py` (1), `backend_detail.py` (1)

---

## Category 2: Configuration/Startup Silencing (5 instances)

### [MEDIUM] Silent termios failure

- **File:** `argus_mcp/cli.py:519-520`
- **Category:** try_except_pass
- **Description:** Terminal state capture failure silently swallowed with bare `pass`. Acceptable since stdin may not be a real terminal, but a debug log would be better.
- **Evidence:**
  ```python
  except Exception:
      pass  # stdin may not be a real terminal
  ```
- **Suggested fix:** `logger.debug("Cannot capture terminal state", exc_info=True)`

### [MEDIUM] Silent terminal restoration failures

- **File:** `argus_mcp/cli.py:593,606,616,621`
- **Category:** try_except_pass
- **Description:** Four nested `try/except Exception: pass` blocks in `_restore_terminal()`. Terminal restoration is inherently best-effort, but catching `Exception` broadly risks masking real errors like `NameError` or `ImportError`.
- **Suggested fix:** Catch `(OSError, ValueError, ImportError)` specifically.

### [MEDIUM] Silent skills state load

- **File:** `argus_mcp/skills/manager.py:220-224`
- **Category:** try_except_pass
- **Description:** `json.load()` failure when loading skill state is silently swallowed with `except Exception: return {}`. A corrupt state file gives no warning.
- **Evidence:**
  ```python
  except Exception:
      return {}
  ```
- **Suggested fix:** Log at debug level with `exc_info=True`.

---

## Category 3: Container Runtime Silencing (6 instances)

### [MEDIUM] Container operation silencing

- **File:** `argus_mcp/bridge/container/runtime.py:193,217,312,334,377,400`
- **Category:** try_except_pass
- **Description:** Container stop/remove/cleanup/network/image operations silently swallow all exceptions. A container that fails to clean up will leak resources.
- **Evidence (line 312):**
  ```python
  except Exception:
      pass  # Image may not exist
  ```
- **Suggested fix:** Log at debug level for expected failures (image not found, network not found); re-raise unexpected ones.

---

## Category 4: Bridge/Server Critical Path (12 instances)

### [MEDIUM] Silent capability discovery failure

- **File:** `argus_mcp/bridge/capability_registry.py:253`
- **Category:** try_except_pass
- **Description:** Individual capability type discovery failure silently caught. If `list_tools()` fails for a backend, no tools are registered and no error is surfaced.
- **Suggested fix:** Log at warning level -- users need to know when discovery fails.

### [MEDIUM] Silent devnull close

- **File:** `argus_mcp/bridge/client_manager.py:1261`
- **Category:** try_except_pass
- **Description:** Devnull file handle close failure swallowed. Low impact but should log.

### [MEDIUM] Silent cleanup operations in client_manager

- **File:** `argus_mcp/bridge/client_manager.py:1292,1302,1334,1348`
- **Category:** try_except_pass
- **Description:** Multiple cleanup operations in `stop_all()` and `disconnect_one()` silently swallow exceptions. These include stack close, state transition, and cleanup operations.

### [MEDIUM] Silent config load in lifespan

- **File:** `argus_mcp/server/lifespan.py:162-165`
- **Category:** try_except_pass
- **Description:** Full config load failure logged at debug level, then all sub-features silently use defaults. This is reasonable but should be at least warning-level since it affects optimizer, telemetry, feature flags, etc.

### [MEDIUM] Silent module reference cleanup

- **File:** `argus_mcp/server/lifespan.py:629-630`
- **Category:** try_except_pass
- **Description:** Module-level reference cleanup silently catches all exceptions. Now logs with `exc_info=True` (improved from previous audit).

### [MEDIUM] Silent handler failures

- **File:** `argus_mcp/server/handlers.py:202`
- **Category:** try_except_pass
- **Description:** Exception caught in handler dispatch without clear error propagation.

---

## Category 5: Secret/Auth Silencing (2 instances)

### [HIGH] Silent secret provider keyring failure

- **File:** `argus_mcp/secrets/providers.py:217-218`
- **Category:** try_except_pass
- **Description:** Keyring name list retrieval failure swallowed. Users cannot know their secrets are not being resolved.

### [MEDIUM] Silent auth discovery logging

- **File:** `argus_mcp/bridge/auth/discovery.py:193,212,279,296`
- **Category:** broad_except
- **Description:** Auth discovery functions catch `Exception as exc` broadly. Most log properly (good), but catch `Exception` where more specific `httpx.HTTPError` or `(ConnectionError, TimeoutError)` would be appropriate.

---

## Category 6: Properly Logged Exception Handlers (Good Practices)

These files demonstrate correct error handling patterns:

- `runtime/service.py` -- Uses `logger.warning(... exc_info=True)` for non-fatal failures
- `bridge/client_manager.py` -- Uses `logger.error()` for stream/connection failures; `_log_task_exception` callback on background tasks
- `server/lifespan.py` -- Uses `logger.exception()` for startup failures
- `config/watcher.py:126` -- Logs config watcher exceptions
- `server/management/router.py` -- Returns proper HTTP error codes (400 for bad input)
- `bridge/auth/store.py` -- Catches specific `OSError` and `json.JSONDecodeError`
- `_task_utils.py` -- Provides shared `_log_task_exception` callback

---

## Category 7: Inconsistent Exception Types

### [LOW] Overly broad `except Exception` where specific types are known

- **File:** `argus_mcp/tui/app.py:455`
- **Category:** broad_except
- **Description:** `except Exception as exc` where only network errors (`httpx.ConnectError`, etc.) are expected. A `TypeError` or `AttributeError` would be silently retried.
- **Suggested fix:** Catch `httpx.HTTPError` or `(ConnectionError, TimeoutError, OSError)`.

### [LOW] TUI settings -- different exception specificity

- **File:** `argus_mcp/tui/settings.py:78-82`
- **Category:** inconsistent
- **Description:** `FileNotFoundError` is caught specifically (good), but the fallback catches `Exception` broadly (bad). The second catch should be `(json.JSONDecodeError, OSError)`.

---

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| TUI widget access silencing | 100+ | LOW |
| Configuration/startup silencing | 5 | MEDIUM |
| Container runtime silencing | 6 | MEDIUM |
| Bridge/server critical path | 12 | MEDIUM |
| Secret/auth silencing | 2 | HIGH/MEDIUM |
| Inconsistent exception types | 2 | LOW |
| **Total broad except clauses** | **264** | -- |

### Improvements Since Previous Audit

| Item | Previous | Current | Status |
|------|----------|---------|--------|
| Transport type detection | Silent pass | Debug log with exc_info | FIXED |
| Client config load | Silent pass | Debug log | FIXED |
| Shutdown body parse | Silent default | Returns 400 | FIXED |
| Token store exceptions | Broad catch | Specific OSError/JSONDecodeError | FIXED |
| Bare `except:` clauses | Unknown | 0 found | GOOD |
