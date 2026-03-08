# Static Analysis Report -- Consolidated

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI (160 files, 28,965 lines)
**Tools:** Ruff, Mypy, Vulture
**Branch:** `feature/build-display-and-timeout-fix`

---

## Ruff (0 findings)

All default Ruff checks pass with zero findings:

```
$ uv run ruff check argus_mcp/ --output-format=grouped
All checks passed!
```

Sub-checks also clean:
- `F401,F841,F811` (unused imports/vars): **0 findings**
- `I001` (unsorted imports): **0 findings**

**Cross-validation:** MCP `ruff-check` tool on `_task_utils.py` confirms zero issues.

**Assessment:** All previously reported Ruff findings (F401 x2, I001 x2 from prior audit) have been resolved.

---

## Mypy (2 errors)

```
$ uv run mypy argus_mcp/ --ignore-missing-imports
```

Checked 160 source files. 2 errors found:

| # | File:Line | Rule | Severity | Description | Evidence | Suggested Fix |
|---|-----------|------|----------|-------------|----------|---------------|
| 1 | `argus_mcp/_task_utils.py:15` | unused-ignore | Low | Unused `type: ignore[type-arg]` comment | `def _log_task_exception(task: asyncio.Task) -> None:  # type: ignore[type-arg]` | Remove the `# type: ignore[type-arg]` comment; mypy no longer flags it |
| 2 | `argus_mcp/bridge/client_manager.py:1613` | unused-coroutine | High | Coroutine return value not awaited -- `store.save()` is async but called without `await` | `store.save(svr_name, tokens)` -- "Value of type Coroutine[Any, Any, None] must be used" | Add `await` before `store.save(svr_name, tokens)` |

**Notes:**
- Finding #2 is a **real bug**: token persistence silently fails because the coroutine is never awaited. This means OAuth tokens obtained via PKCE flow are not persisted to disk.
- Finding #1 is a stale type-ignore comment that can be safely removed.

---

## Vulture (0 findings at >=80% confidence)

```
$ uv run vulture argus_mcp/ --min-confidence 80
(no output)
```

All previously reported Vulture findings (signal handler unused variables, unreachable code in `tui/screens/base.py`) have been resolved.

**Extended scan at 60% confidence:** 250+ items reported, but these are framework-level false positives (Textual TUI lifecycle methods like `compose`, `on_mount`, `watch_*`, `on_button_pressed`, dataclass fields, HTTP handler methods, etc.). No true positives at 60% that are not framework artifacts.

---

## Syntax Check

```
$ python -m py_compile <key files>
All syntax checks passed
```

Verified: `cli.py`, `server/lifespan.py`, `bridge/client_manager.py`, `runtime/service.py` -- no syntax errors.

---

## MCP Tool Cross-Validation

| Tool | Target | Result |
|------|--------|--------|
| `mcp__analyzer__ruff-check` | `_task_utils.py` | 0 issues (confirmed) |

---

## Grand Total

| Tool | Findings |
|------|----------|
| Ruff | 0 |
| Mypy | 2 |
| Vulture (>=80%) | 0 |
| Syntax | 0 |
| **Total** | **2** |

---

## Comparison with Prior Audit

| Tool | Prior Audit | Current | Delta |
|------|-------------|---------|-------|
| Ruff | 4 | 0 | -4 (all fixed) |
| Mypy | 5 | 2 | -3 (improved) |
| Vulture | 5 | 0 | -5 (all fixed) |
| **Total** | **14** | **2** | **-12** |

The codebase has improved significantly since the prior audit. The two remaining mypy findings should be addressed, especially the missing `await` in `client_manager.py:1613` which is a functional bug.
