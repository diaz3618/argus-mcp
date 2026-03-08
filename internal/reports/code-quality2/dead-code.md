# Dead Code Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI (160 files, 28,965 lines)
**Tools:** Ruff (F401, F841, I001), Vulture
**Branch:** `feature/build-display-and-timeout-fix`

---

## Ruff F401 -- Unused Imports (0 findings)

```
$ uv run ruff check argus_mcp/ --select F401 --output-format=grouped
All checks passed!
```

All previously flagged unused imports (`RUNTIME_DEFAULTS`, `ValidationError` in `bridge/container/templates/_generators.py`) have been resolved.

---

## Ruff F841 -- Unused Variables (0 findings)

```
$ uv run ruff check argus_mcp/ --select F841 --output-format=grouped
All checks passed!
```

---

## Ruff I001 -- Unsorted Imports (0 findings)

```
$ uv run ruff check argus_mcp/ --select I001 --output-format=grouped
All checks passed!
```

All previously flagged import sorting issues (`templates/models.py`, `templates/validation.py`) have been resolved.

---

## Vulture -- Unused Code (>=80% confidence): 0 findings

```
$ uv run vulture argus_mcp/ --min-confidence 80
(no output)
```

All previously reported items (signal handler variables in `server/lifespan.py`, unreachable code in `tui/screens/base.py`) have been resolved.

---

## Vulture -- Extended Scan (>=60% confidence): 250+ items

At 60% confidence, Vulture reports many items across the codebase. After manual analysis, these fall into the following categories:

### Category 1: Textual TUI Framework Methods (False Positives)

These are lifecycle/event methods called by the Textual framework, not by application code directly. They are NOT dead code.

| Pattern | Count | Examples |
|---------|-------|---------|
| `compose()` | ~20 | All TUI widget/screen classes |
| `on_mount()` | ~15 | Widget initialization hooks |
| `on_button_pressed()` | ~10 | Button event handlers |
| `on_input_changed()` | ~5 | Input event handlers |
| `watch_*()` | ~5 | Reactive property watchers |
| `DEFAULT_CSS` | ~15 | CSS class variables |
| `BINDINGS` | ~10 | Key binding declarations |
| `cursor_type`, `zebra_stripes` | ~10 | DataTable configuration attrs |

**Verdict:** All false positives -- Textual framework convention.

### Category 2: Dataclass/Model Fields (False Positives)

Fields on dataclass and Pydantic models used via serialization or external access:

| File | Fields |
|------|--------|
| `audit/models.py` | `client_ip`, `user_id`, `outcome` |
| `bridge/auth/discovery.py` | `response_types_supported` |
| `bridge/container/templates/models.py` | `package_clean`, `is_alpine`, `install_cmd`, `go_package_clean`, `container_uid`, `container_user`, `container_home` |

**Verdict:** False positives -- accessed via attribute access patterns or serialization.

### Category 3: HTTP Handler Override Methods (False Positives)

| File:Line | Method | Reason |
|-----------|--------|--------|
| `bridge/auth/pkce.py:119` | `do_GET` | BaseHTTPRequestHandler override |
| `bridge/auth/pkce.py:180` | `log_message` | BaseHTTPRequestHandler override |

**Verdict:** False positives -- called by Python's HTTP server framework.

### Category 4: Interface/Protocol Methods (False Positives)

Methods that implement an interface or are called via base class references:

| File | Method | Reason |
|------|--------|--------|
| `bridge/container/runtime.py:55` | `from_str` | Classmethod called via base reference |
| `bridge/container/runtime.py:79,156,426` | `runtime_type` | Property on ABC implementations |
| `bridge/container/runtime.py:135,366,503` | `remove_network` | ABC interface method |
| `bridge/container/runtime.py:139,380,506` | `list_images` | ABC interface method |

**Verdict:** False positives -- ABC/interface implementations.

### Category 5: Potentially Unused Code (Requires Manual Review)

These items at 60% confidence may be genuinely unused but require human review to confirm:

| # | File:Line | Type | Item | Confidence | Notes |
|---|-----------|------|------|------------|-------|
| 1 | `bridge/auth/discovery.py:137` | function | `discover_from_401` | 60% | May be called dynamically or reserved for future use |
| 2 | `bridge/auth/store.py:154` | method | `list_backends` | 60% | Could be used by TUI or CLI |
| 3 | `bridge/auth/token_cache.py:54` | method | `invalidate` | 60% | Cache invalidation -- may be needed |
| 4 | `bridge/client_manager.py:263` | attribute | `_current_build_name` | 60% | Set but possibly never read |
| 5 | `bridge/client_manager.py:1375` | method | `get_all_status_records` | 60% | Status query method |
| 6 | `bridge/container/__init__.py:64` | function | `_reset_health_cache` | 60% | Test utility or debug helper |
| 7 | `bridge/container/network.py:45` | function | `build_network_args` | 60% | May be called from templates |
| 8 | `bridge/container/network.py:54` | function | `ensure_managed_network` | 60% | May be called from runtime |
| 9 | `bridge/container/runtime.py:166` | method | `reset_health_cache` | 60% | Health management utility |
| 10 | `bridge/container/runtime.py:683` | function | `check_runtime_health` | 60% | Health check entry point |
| 11 | `bridge/elicitation.py:94-189` | class | `ElicitationBridge` + methods | 60% | Entire elicitation module may be unused scaffolding |
| 12 | `bridge/filter.py:59` | function | `build_filter` | 60% | Filter construction helper |
| 13 | `bridge/groups.py:65-85` | methods | `all_servers`, `group_summary`, `add_server`, `remove_server` | 60% | Group management methods |
| 14 | `bridge/health/checker.py:146-150` | methods | `get_all_health`, `reset_backend` | 60% | Health query methods |
| 15 | `bridge/middleware/auth.py:25` | class | `AuthMiddleware` | 60% | Entire middleware may be unused |
| 16 | `bridge/middleware/authz.py:28` | class | `AuthzMiddleware` | 60% | Entire middleware may be unused |

**Verdict:** These are low-confidence flags. Items #11, #15, #16 (entire classes flagged) are the most likely candidates for genuinely dead code and should be verified.

---

## Mypy-Detected Dead Code Patterns

| # | File:Line | Type | Description |
|---|-----------|------|-------------|
| 1 | `_task_utils.py:15` | stale-ignore | `# type: ignore[type-arg]` no longer needed |

---

## Summary Table

| Category | Count | Status |
|----------|-------|--------|
| Ruff F401 (unused imports) | 0 | Clean |
| Ruff F841 (unused variables) | 0 | Clean |
| Ruff I001 (unsorted imports) | 0 | Clean |
| Vulture >=80% confidence | 0 | Clean |
| Vulture 60% -- framework false positives | ~90 | No action needed |
| Vulture 60% -- dataclass false positives | ~10 | No action needed |
| Vulture 60% -- requires manual review | 16 | Review recommended |
| Mypy stale ignores | 1 | Remove comment |
| **Actionable total** | **17** | |

---

## Comparison with Prior Audit

| Category | Prior | Current | Delta |
|----------|-------|---------|-------|
| F401 unused imports | 2 | 0 | -2 (fixed) |
| I001 unsorted imports | 2 | 0 | -2 (fixed) |
| Vulture >=80% | 5 | 0 | -5 (fixed) |
| **High-confidence total** | **9** | **0** | **-9** |

All high-confidence dead code findings from the prior audit have been resolved. The remaining items are low-confidence vulture flags that require human judgment to determine if they are genuinely unused.
