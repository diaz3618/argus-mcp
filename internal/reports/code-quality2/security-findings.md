# Security Findings Report

**Generated:** 2026-03-07
**Scope:** Full `argus_mcp/` including TUI (22,962 LOC scanned by Bandit)
**Tools:** Bandit 1.9.4, OSV-Scanner, Manual inspection (grep-based)

---

## Severity Distribution

| Severity | Count | Source |
|----------|-------|--------|
| HIGH | 0 | Bandit |
| MEDIUM | 4 | Bandit B104 (x3), B108 (x1) |
| LOW | 104 | Bandit B110 (89), B105 (3), B106 (2), B101 (2), B404 (3), B603 (3), B607 (2) |
| MANUAL-HIGH | 1 | Monkey-patching surface |
| MANUAL-MEDIUM | 3 | SSRF surface, subprocess, tainted URL |
| MANUAL-WARNING | 11 | Credential-adjacent logging |
| **Total** | **123** | |

---

## HIGH Severity

### [HIGH] Jinja2 autoescape disabled -- Mitigated in current code

- **File:** `argus_mcp/bridge/container/templates/engine.py:29-35`
- **Tool:** Manual inspection (Bandit B701 no longer triggers)
- **Rule:** B701 / direct-use-of-jinja2
- **Description:** The `jinja2.Environment` uses `select_autoescape(default_for_string=False, default=False)`, which effectively disables autoescape. However, this is intentional and documented: templates generate Dockerfiles (plain text), not HTML. Enabling HTML autoescape would corrupt shell commands and file paths.
- **Evidence:**
  ```python
  # Autoescape is intentionally disabled: these templates generate
  # Dockerfiles (plain text), not HTML.
  _env = jinja2.Environment(
      loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
      undefined=jinja2.StrictUndefined,
      autoescape=jinja2.select_autoescape(
          default_for_string=False,
          default=False,
      ),
      keep_trailing_newline=True,
      trim_blocks=True,
      lstrip_blocks=True,
  )
  ```
- **Assessment:** Mitigated. `StrictUndefined` prevents missing variable injection. The `select_autoescape` call satisfies Bandit B701. Template context values should still be validated at the caller level to prevent Dockerfile injection.
- **Suggested fix:** Add input validation/sanitization for template context values in `render_template()` callers, especially any values sourced from user configuration.

---

## WARNING Severity -- Credential-Adjacent Logging (11 findings)

### [WARNING] OAuth token request URL logged

- **File:** `argus_mcp/bridge/auth/provider.py:114`
- **Tool:** Manual grep
- **Rule:** python-logger-credential-disclosure
- **Description:** The token endpoint URL is logged at debug level. While no credentials are logged, the URL reveals OAuth infrastructure.
- **Evidence:**
  ```python
  logger.debug("OAuth2 token request -> %s", self._token_url)
  ```

### [WARNING] Token exchange failure logged

- **File:** `argus_mcp/bridge/auth/pkce.py:387-390`
- **Tool:** Manual grep
- **Rule:** python-logger-credential-disclosure
- **Description:** Token exchange failure logs HTTP status code. The response body is no longer logged (improvement from previous audit).
- **Evidence:**
  ```python
  logger.error("Token exchange failed: HTTP %d", resp.status_code)
  ```

### [WARNING] Token refresh failure logged

- **File:** `argus_mcp/bridge/auth/provider.py:240-243`
- **Tool:** Manual grep
- **Rule:** python-logger-credential-disclosure
- **Description:** Token refresh failure logs the exception type name, which could reveal OAuth configuration issues.
- **Evidence:**
  ```python
  logger.warning("[%s] Token refresh failed, will re-authenticate: %s",
                 self._backend_name, type(exc).__name__)
  ```

### [WARNING] Token saved/deleted/expired messages logged (5 findings)

- **Files:**
  - `argus_mcp/bridge/auth/store.py:79` -- Token saved for backend (debug)
  - `argus_mcp/bridge/auth/store.py:84` -- Failed to save token (warning)
  - `argus_mcp/bridge/auth/store.py:104` -- Failed to read token (warning)
  - `argus_mcp/bridge/auth/store.py:117` -- Stored token expired (debug)
  - `argus_mcp/bridge/auth/store.py:150` -- Token deleted (debug)
- **Tool:** Manual grep
- **Rule:** python-logger-credential-disclosure
- **Description:** Token lifecycle events are logged with backend names. No actual token values are logged. These are debug-level and useful for troubleshooting, but backend names could aid reconnaissance.
- **Suggested fix:** Acceptable risk at debug level. Ensure production deployments use INFO or higher log level.

### [WARNING] Token directory creation failure logged

- **File:** `argus_mcp/bridge/auth/store.py:173`
- **Tool:** Manual grep
- **Rule:** python-logger-credential-disclosure
- **Description:** Failed directory creation logs the directory path and OS error.
- **Evidence:**
  ```python
  logger.warning("Failed to create token directory %s: %s", self._dir, exc)
  ```

### [WARNING] Secret resolution logged

- **File:** `argus_mcp/secrets/resolver.py:107`
- **Tool:** Manual grep
- **Rule:** python-logger-credential-disclosure
- **Description:** Secret name and resolution path are logged at debug level. The actual secret value is NOT logged. A nosemgrep comment documents the rationale.
- **Evidence:**
  ```python
  # nosemgrep: python-logger-credential-disclosure (logs secret name, not value)
  logger.debug("Resolved secret '%s' at %s", secret_name, path)
  ```

### [WARNING] Secret store operations logged

- **File:** `argus_mcp/secrets/store.py:44,50`
- **Tool:** Manual grep
- **Rule:** python-logger-credential-disclosure
- **Description:** Secret name and provider type logged at debug level during store/delete operations.

### [WARNING] Management API token env var logged

- **File:** `argus_mcp/server/management/auth.py:39`
- **Tool:** Manual grep
- **Rule:** python-logger-credential-disclosure
- **Description:** Logs which environment variable the management token was resolved from (not the token value itself).
- **Evidence:**
  ```python
  logger.debug("Management API token resolved from %s env var.", MGMT_TOKEN_ENV_VAR)
  ```

---

## MEDIUM Severity -- Bandit

### [MEDIUM] B104: Possible binding to all interfaces (3 findings)

#### Finding 1: OAuth localhost address set includes 0.0.0.0

- **File:** `argus_mcp/server/management/auth.py:67`
- **Tool:** Bandit
- **Rule:** B104
- **Severity:** MEDIUM | Confidence: MEDIUM
- **Description:** `0.0.0.0` is included in `_LOCALHOST_ADDRS` frozenset. This is used for comparison (checking if a bind address is localhost), not for actual binding. The inclusion means requests from `0.0.0.0` are treated as localhost, which is technically correct but permissive.
- **Evidence:**
  ```python
  _LOCALHOST_ADDRS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})
  ```
- **Suggested fix:** Consider removing `0.0.0.0` from the localhost set if the intent is to restrict to actual loopback addresses only.

#### Finding 2: 0.0.0.0 in allowed origins

- **File:** `argus_mcp/server/origin.py:42`
- **Tool:** Bandit
- **Rule:** B104
- **Severity:** MEDIUM | Confidence: MEDIUM
- **Description:** `0.0.0.0` is included in the default allowed origins set. This permits CORS requests with an origin containing `0.0.0.0`.
- **Evidence:**
  ```python
  "0.0.0.0",
  ```

#### Finding 3: Session lookup matches 0.0.0.0

- **File:** `argus_mcp/sessions.py:240`
- **Tool:** Bandit
- **Rule:** B104
- **Severity:** MEDIUM | Confidence: MEDIUM
- **Description:** Session lookup logic treats `0.0.0.0` as matching any host. This is standard behavior for wildcard bind addresses.
- **Evidence:**
  ```python
  if info.port == port and (info.host == host or info.host == "0.0.0.0"):
  ```

### [MEDIUM] B108: Hardcoded /tmp directory

- **File:** `argus_mcp/bridge/container/wrapper.py:320`
- **Tool:** Bandit
- **Rule:** B108
- **Severity:** MEDIUM | Confidence: MEDIUM
- **Description:** Hardcoded `/tmp` path used in container tmpfs mount arguments. This is inside a container context (not the host), so the risk is mitigated.
- **Evidence:**
  ```python
  args.extend(["--tmpfs", "/tmp:rw,nosuid,size=64m,mode=1777"])
  ```
- **Suggested fix:** No action needed. The `/tmp` reference is for the container filesystem, not the host. `nosuid` and size limits are appropriately applied.

---

## MANUAL Findings

### [MANUAL-HIGH] Monkey-patching creates implicit security surface

- **File:** `argus_mcp/server/lifespan.py:153-273`
- **Tool:** Manual inspection
- **Rule:** monkey-patch-security
- **Description:** 15 attributes are dynamically set on `mcp_svr_instance` including security-sensitive components: `manager`, `registry`, `audit_logger`, `middleware_chain`, `session_manager`, `feature_flags`, `skill_manager`, `optimizer_index`, `version_checker`, and `composite_tools`. Any code that accesses these via `getattr()` (20+ call sites in `server/handlers.py` and `server/lifespan.py`) has no compile-time guarantee the attribute exists or is of the expected type, creating a potential for type confusion if the server object is accessible from untrusted contexts.
- **Evidence (attribute assignments):**
  ```python
  mcp_svr_instance.manager = service.manager
  mcp_svr_instance.registry = service.registry
  mcp_svr_instance.audit_logger = audit_logger
  mcp_svr_instance.middleware_chain = chain
  mcp_svr_instance.session_manager = session_manager
  mcp_svr_instance.feature_flags = FeatureFlags(ff_overrides)
  mcp_svr_instance.version_checker = VersionChecker()
  mcp_svr_instance.skill_manager = skill_manager
  # ... and 7 more
  ```
- **Evidence (getattr access pattern in handlers.py):**
  ```python
  chain = getattr(mcp_server, "middleware_chain", None)
  composite_tools = getattr(mcp_server, "composite_tools", None) or []
  optimizer = getattr(mcp_server, "optimizer_index", None)
  optimizer_enabled = getattr(mcp_server, "optimizer_enabled", False)
  ```
- **Suggested fix:** Create a typed `ServerState` dataclass and attach it as a single attribute, replacing the 15+ individual `setattr` calls. This provides type safety and a single point of validation.

### [MANUAL-MEDIUM] SSRF surface in OAuth discovery

- **File:** `argus_mcp/bridge/auth/discovery.py:109,153`
- **Tool:** Manual inspection
- **Rule:** ssrf-via-config
- **Description:** The OAuth discovery module makes outbound HTTP requests to URLs derived from MCP server URLs and WWW-Authenticate headers. The `mcp_server_url` originates from user configuration. While `follow_redirects=True` is set (which can amplify SSRF), the timeout of 10-30s limits the blast radius.
- **Evidence:**
  ```python
  async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
      auth_server_url = await _discover_resource_metadata(client, mcp_server_url)
  ```
- **Suggested fix:** Consider adding URL validation (scheme allowlist: `https` only in production, optional `http` for localhost/dev). Add a blocklist for internal/private IP ranges if the server runs in a cloud environment.

### [MANUAL-MEDIUM] Tainted URL construction in management API

- **File:** `argus_mcp/server/management/router.py:118-121`
- **Tool:** Manual inspection
- **Rule:** tainted-url-host
- **Description:** `host` and `port` from `request.app.state` are interpolated into URL strings. These values are set during server startup from CLI args (documented with `nosec` comments), not from user request data. However, static analysis cannot verify this flow.
- **Evidence:**
  ```python
  host = getattr(request.app.state, "host", "127.0.0.1")  # nosec: not user-controlled
  port = getattr(request.app.state, "port", 0)  # nosec: not user-controlled
  sse_url = f"http://{host}:{port}{SSE_PATH}"
  ```
- **Suggested fix:** Use `urllib.parse.urlunparse()` for URL construction, or validate `host` against an allowlist.

### [MANUAL-MEDIUM] Subprocess usage without shell=True (safe pattern)

- **File:** `argus_mcp/cli.py:228`, `argus_mcp/tui/screens/client_config.py:228`
- **Tool:** Bandit B603/B607, Manual verification
- **Rule:** subprocess-usage
- **Description:** Two subprocess call sites exist. Both use list arguments (no shell=True), which is the safe pattern. The `cli.py:228` call uses `subprocess.Popen` for detaching child processes. The `client_config.py:228` call invokes `xclip` for clipboard operations with a 2s timeout.
- **Evidence (cli.py:228):**
  ```python
  proc = subprocess.Popen(
      cmd,
      stdout=out_fd,
      stderr=out_fd,
      stdin=subprocess.DEVNULL,
      start_new_session=True,
      env=child_env,
  )
  ```
- **Evidence (client_config.py:228):**
  ```python
  proc = subprocess.run(
      ["xclip", "-selection", "clipboard"],
      input=snippet.encode(),
      capture_output=True,
      timeout=2,
  )
  ```
- **Assessment:** Both are safe. No `shell=True`, no user-controlled arguments. The `cmd` in `cli.py` is constructed internally from known Python executable paths.

---

## LOW Severity -- Bandit (Summary)

| Rule | Count | Description | Assessment |
|------|-------|-------------|------------|
| B110 | 89 | `try_except_pass` | Primarily in TUI code (app.py: 18, setup_wizard: 6). Acceptable for UI resilience but masks errors. |
| B105 | 3 | Hardcoded password string | False positives: empty string default `""`, OAuth `"none"` auth method, env var name `"ARGUS_MGMT_TOKEN"` |
| B106 | 2 | Hardcoded password funcarg | False positives: empty `access_token=""` for expired tokens, `token_pattern` regex for TfidfVectorizer |
| B404 | 3 | `import subprocess` | Informational only -- subprocess usage is safe (see MANUAL findings) |
| B603 | 3 | Subprocess without shell check | Safe -- no `shell=True` used anywhere |
| B607 | 2 | Partial executable path | `stty` and `xclip` -- standard system utilities |
| B101 | 2 | `assert` used | Both in `pkce.py` with `noqa: S101` comments, used for internal invariant checks |

### B110 Distribution (top 10 files)

| File | Count |
|------|-------|
| `tui/app.py` | 18 |
| `tui/screens/setup_wizard.py` | 6 |
| `cli.py` | 5 |
| `tui/widgets/optimizer_panel.py` | 5 |
| `tui/widgets/otel_panel.py` | 5 |
| `tui/widgets/workflows_panel.py` | 5 |
| `tui/screens/audit_log.py` | 4 |
| `tui/screens/tools.py` | 4 |
| `tui/screens/health.py` | 3 |
| `tui/screens/settings.py` | 3 |

---

## File Permissions

| File | Pattern | Permission | Assessment |
|------|---------|------------|------------|
| `argus_mcp/bridge/auth/store.py:78` | `os.chmod(path, 0o600)` | Owner-only read/write | Correct for token files |
| `argus_mcp/bridge/auth/store.py:171` | `os.chmod(self._dir, 0o700)` | Owner-only rwx | Correct for token directory |
| `argus_mcp/secrets/providers.py:147` | `os.chmod(self._path, 0o600)` | Owner-only read/write | Correct for secrets file |

All file permission patterns are appropriately restrictive. No findings.

---

## Dependency Security

### OSV-Scanner Results

- **Tool:** osv-scanner 1.x
- **Lockfile:** `uv.lock` (82 packages)
- **Result:** 0 vulnerabilities found
- **Status:** Clean dependency tree as of scan date (2026-03-07)

### pip-audit Results

- **Status:** Not available (not installed in project venv)
- **Note:** OSV-Scanner provides equivalent coverage via the OSV database

---

## Absent Vulnerability Classes

The following common vulnerability classes were checked and **not found**:

| Class | Search Pattern | Result |
|-------|---------------|--------|
| `eval()`/`exec()` | `\beval\(\|\bexec\(` | Not found |
| `pickle.loads` | `pickle\.loads` | Not found |
| `yaml.unsafe_load` | `yaml\.load\(\|yaml\.unsafe_load` | Not found |
| `shell=True` | `shell=True` | Not found |
| `os.system()` | `os\.system` | Not found (removed since prior audit) |
| SQL injection | string-built SQL | Not applicable (no SQL usage) |
| XSS | unsanitized HTML output | Not applicable (no HTML rendering) |

---

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| Jinja2 autoescape | 1 | Mitigated (intentional for Dockerfile generation) |
| Credential-adjacent logging | 11 | WARNING (no actual secrets logged) |
| Hardcoded bind 0.0.0.0 | 3 | MEDIUM (comparison/config use, not actual binding) |
| Hardcoded /tmp | 1 | MEDIUM (container context, mitigated) |
| Monkey-patch surface | 1 | HIGH (15 dynamic attributes on mcp_server) |
| SSRF surface | 1 | MEDIUM (config-driven URLs, follow_redirects=True) |
| Tainted URL construction | 1 | MEDIUM (CLI-sourced, not user-request-sourced) |
| Subprocess usage | 2 | SAFE (no shell=True, no user input) |
| try_except_pass (B110) | 89 | LOW (mostly TUI resilience) |
| Other LOW (B105/B106/B101/B404/B603/B607) | 15 | LOW (false positives / informational) |
| File permissions | 3 | SAFE (all correctly restrictive) |
| Dependency vulns | 0 | CLEAN |
| **Total findings** | **108 (Bandit) + 15 (Manual) = 123** | |

### Changes Since Prior Audit

| Item | Prior Report | Current | Status |
|------|-------------|---------|--------|
| Jinja2 B701 | HIGH (no autoescape) | Mitigated | Fixed: `select_autoescape` added with documented rationale |
| `os.system()` in cli.py | HIGH | Removed | Fixed: `os.system("stty sane")` fallback eliminated |
| B110 try_except_pass | 98 | 89 | Improved (-9) |
| Credential logging | 10 (Semgrep) | 11 (Manual grep) | Similar -- response body logging removed from pkce.py |
| Dependency vulns | 0 | 0 | Clean |
