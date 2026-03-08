# Code Quality Analysis -- Executive Summary

**Project:** argus-mcp
**Branch:** `feature/build-display-and-timeout-fix`
**Date:** 2026-03-07
**Scope:** 160 Python files, 28,965 lines (full `argus_mcp/` including TUI)

---

## Total Findings by Severity

| Severity | Count | Sources |
|----------|-------|---------|
| CRITICAL | 1 | Missing input validation at HTTP boundaries (ai-agent-patterns) |
| HIGH | 5 | Mypy unawaited coroutine (1), monkey-patching surface (1), blocking I/O in async (1), swallowed exceptions pattern (1), secret provider silencing (1) |
| MEDIUM | 37 | Bandit B104/B108 (4), SSRF surface (1), tainted URL (1), naming inconsistency (1), blocking I/O (3), race conditions (2), missing cancellation (2), fire-and-forget (1), over-engineering (1), copy-paste patterns (5), config/startup silencing (5), container runtime silencing (6), bridge/server silencing (5) |
| LOW | 120 | Bandit B110 try_except_pass (89), B105/B106/B101/B404/B603/B607 (15), naming (5), docstrings (2), type annotations (2), TUI widget silencing (100+), unnecessary copies (4), sleep patterns (3) |
| INFO | 12 | Ruff formatting (12 files), credential-adjacent logging (11) |
| MAINTAINABILITY | 93 | Radon CC grade D (8), grade C (48), MI grade C (1), files >500 lines (14), classes >7 methods (8), functions >40 lines (14) |

**Estimated total distinct findings: 268+**

---

## Tool Result Summary

| Tool | Findings | Key Issue |
|------|----------|-----------|
| **Ruff check** | 0 | All checks pass (was 4 in prior audit) |
| **Ruff format** | 12 files | Formatting inconsistencies across bridge, server, TUI, workflows |
| **Mypy** | 2 | 1 unawaited coroutine (bug), 1 stale type-ignore |
| **Vulture (>=80%)** | 0 | Clean (was 5 in prior audit) |
| **Vulture (60%)** | 16 | Potentially unused code requiring manual review |
| **Bandit** | 108 | 0 HIGH, 4 MEDIUM (B104/B108), 104 LOW (89 try_except_pass) |
| **OSV-Scanner** | 0 | 82 packages scanned, no vulnerabilities |
| **Radon CC** | 56 | 8 grade D (CC >= 20), 48 grade C (CC 11-19) |
| **Radon MI** | 1 | `client_manager.py` = grade C (2.27) -- very low maintainability |
| **Manual/Grep** | 70+ | Monkey-patching, blocking I/O, race conditions, naming, duplicates |

---

## Top-10 Critical Issues

### 1. Missing Input Validation at HTTP Boundaries
- **File:** `argus_mcp/server/management/router.py:374,468`
- **Impact:** No bounds on `timeout` (0 to infinity) or `limit` (memory exhaustion) parameters
- **Tools:** Manual, ai-agent-patterns

### 2. Unawaited Coroutine: `store.save()` -- Token Persistence Bug
- **File:** `argus_mcp/bridge/client_manager.py:1613`
- **Impact:** OAuth tokens obtained via PKCE flow are silently never persisted to disk
- **Tools:** Mypy (unused-coroutine)

### 3. 264 Broad `except Exception` Clauses
- **Across:** 30+ files, TUI alone has 100+ instances
- **Impact:** Silent failures mask bugs, data corruption, security issues
- **Tools:** Bandit B110, Grep

### 4. 13 Monkey-Patched Attributes on `mcp_server`
- **File:** `argus_mcp/server/lifespan.py:153-273`
- **Impact:** No type safety, no IDE support, fragile coupling, silent attribute typos
- **Tools:** Manual, Mypy

### 5. God Object: `ClientManager` -- MI=2.27
- **File:** `argus_mcp/bridge/client_manager.py` (1,757 lines)
- **Impact:** Single most complex file; any change risks regressions
- **Tools:** Radon MI, Radon CC

### 6. SSRF Surface in OAuth Discovery
- **File:** `argus_mcp/bridge/auth/discovery.py:109,153`
- **Impact:** Config-driven URLs with `follow_redirects=True` could enable SSRF
- **Tools:** Manual

### 7. Blocking I/O in Async Context (2 remaining)
- **Files:** `config/loader.py:70-71`, `bridge/client_manager.py:355`
- **Impact:** Blocks event loop during config reads and devnull initialization
- **Tools:** Manual

### 8. 45% of Modules Lack Dedicated Tests
- **Across:** 5 HIGH-priority untested modules (cli.py, service.py, tui/app.py, auth/store.py, auth/discovery.py)
- **Impact:** No regression safety net for critical paths
- **Tools:** Manual file mapping

### 9. Duplicate Config Discovery Logic (6 implementations)
- **Files:** `config/loader.py`, `setup_wizard.py`, `tool_editor.py`, `skills.py`, `registry.py`, `_dev_launch.py`
- **Impact:** Config file search behavior differs by call site
- **Tools:** Grep

### 10. Complexity Hotspot: `_discover_caps_by_type()` CC=29
- **File:** `argus_mcp/bridge/capability_registry.py:59`
- **Impact:** 198-line method with 29 branch points, high bug risk
- **Tools:** Radon CC

---

## AI Coding Agent Pattern Assessment

Based on research from IEEE Spectrum, CodeRabbit, Endor Labs, and Veracode (2025-2026):

| Pattern | Found? | Count | Details |
|---------|--------|-------|---------|
| Missing input validation | YES | 3+ | No bounds on timeout/limit HTTP params |
| Swallowed exceptions | YES | 264 | `except Exception` epidemic |
| Logic errors (silent typos) | YES | 13 | Monkey-patched attributes vulnerable to typos |
| Inconsistent error handling | YES | 3+ | Different patterns for same error types |
| Over-engineering | YES | 3+ | Middleware chain, abstract factories, state machine |
| Blocking in async | YES | 2 | `open()`, `yaml.safe_load()` in async functions |
| God objects | YES | 3 | ClientManager (1,757L), ArgusApp (958L), ArgusService (849L) |
| Monkey-patching | YES | 13 | Attributes injected onto `mcp_server` |
| Inconsistent naming | YES | 3+ | `svr_name` vs `server_name` vs `backend_name` |
| Resource leaks | YES | 2 | Unclosed file descriptors in error paths |
| Race conditions | YES | 2 | TUI flags, lazy devnull init |
| Fire-and-forget tasks | YES | 1 | registry.py create_task without callback |
| Copy-paste code | YES | 10 patterns | 320+ instances of duplicated logic |
| Missing type narrowing | YES | 30+ | `Any`/`Optional` without narrowing |
| Hardcoded values | YES | 20+ | Inline timeouts across codebase |

**Detection rate: 13 of 15 known AI patterns detected** (down from 13/15 previously, with significant improvements in blocking I/O and fire-and-forget categories).

---

## Improvements Since Prior Audit

| Area | Previous | Current | Change |
|------|----------|---------|--------|
| Ruff findings | 4 | 0 | -100% |
| Mypy findings | 5 | 2 | -60% |
| Vulture (>=80%) | 5 | 0 | -100% |
| Bandit B110 | 98 | 89 | -9% |
| Fire-and-forget tasks | 7 unhandled | 1 unhandled | -86% |
| Blocking I/O in async | 8 | 2 | -75% |
| Event loop monkey-patching | Present | Eliminated | FIXED |
| Event ID race condition | Counter w/o lock | uuid4() | FIXED |
| `os.system()` usage | Present | Removed | FIXED |
| Jinja2 autoescape | Missing | Addressed (select_autoescape) | FIXED |
| `start_all()` CC | 44 (Grade F) | 11 (Grade C) | -75% |
| Token store I/O | Sync in async | asyncio.to_thread() | FIXED |

---

## Report Index

| # | Report | Focus |
|---|--------|-------|
| 1 | `summary.md` | This file |
| 2 | `static-analysis.md` | Ruff, Mypy, Vulture consolidated results |
| 3 | `dead-code.md` | Unused imports, variables, unreachable code |
| 4 | `security-findings.md` | Bandit, OSV-Scanner, manual security review |
| 5 | `modularity.md` | File/function size, complexity, god objects |
| 6 | `performance.md` | Blocking I/O, complexity hotspots, polling |
| 7 | `duplicate-logic.md` | Copy-pasted patterns, repeated code |
| 8 | `error-handling.md` | All 264 broad except clauses, silencing patterns |
| 9 | `async-antipatterns.md` | Fire-and-forget, blocking, race conditions |
| 10 | `ai-agent-patterns.md` | AI coding smell assessment (13/15 detected) |
| 11 | `naming-and-conventions.md` | Naming inconsistencies, formatting, docstrings |
| 12 | `test-coverage-gaps.md` | Module-to-test mapping, untested code |
