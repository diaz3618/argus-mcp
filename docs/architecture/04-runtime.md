# Service Lifecycle

The `ArgusService` class orchestrates the entire runtime: loading config,
managing backend connections, and coordinating subsystems.

## ArgusService

`argus_mcp/runtime/service.py` is the central orchestrator.

### Startup (`service.start(config_path)`)

```
1. Load and validate config file
2. Resolve secret:name references via SecretStore
3. Initialize ClientManager with backend configs
4. Start auth discovery (non-blocking asyncio.create_task)
5. StartupCoordinator 3-phase backend initialization:
   Phase 1 — Launch remote tasks:
     - Sort backends by _TYPE_PRIORITY (streamable-http=0, sse=1, stdio=2)
     - Start all remote backends (SSE + streamable-http) concurrently
     - Respect STARTUP_CONCURRENCY limit with STARTUP_STAGGER_DELAY
   Phase 2 — Build and connect stdio:
     - Process stdio backends sequentially
     - For each: detect runtime → classify command → build image → create container
     - Wrap StdioServerParameters to use "docker start -ai"
   Phase 3 — Gather remote results:
     - Await all remote tasks from Phase 1
     - Collect results and errors
6. Build CapabilityRegistry from connected backends
7. Apply conflict resolution, filters, renames
8. Initialize subsystems:
   - AuditLogger (if enabled)
   - HealthChecker
   - GroupManager
   - ToolIndex (if optimizer enabled)
   - FeatureFlags
9. Report status via display/installer.py (Rich Live)
```

### Shutdown (`service.stop()`)

```
1. Stop health checker
2. Disconnect all backends gracefully
3. Clean up all pre-created containers (cleanup_all_containers)
4. Close audit logger
5. Clean up resources
```

### Hot-Reload (`service.reload()`)

```
1. Re-read config file
2. Diff against current config
3. Stop removed backends
4. Start added backends
5. Reconnect changed backends
6. Rebuild capability registry
7. Report changes
```

### Reconnect (`service.reconnect(backend_name)`)

Reconnects a single backend without affecting others. Useful for recovering
from transient failures.

## Runtime Models

`argus_mcp/runtime/models.py` defines status models:

### BackendPhase

Six-phase lifecycle enum tracking each backend's state:

| Phase | Description |
|-------|-------------|
| `PENDING` | Configured, not started |
| `INITIALIZING` | Connection in progress |
| `READY` | Connected, serving capabilities |
| `DEGRADED` | Health check failing but connected |
| `FAILED` | Connection error |
| `SHUTTING_DOWN` | Disconnecting |

### BackendCondition

Structured status conditions attached to each backend:

```python
BackendCondition(
    type="Ready",
    status=True,
    reason="Connected",
    message="Backend initialized successfully",
    last_transition="2026-02-23T12:00:00Z"
)
```

### BackendStatusRecord

Combines phase, conditions, and metadata for each backend. Tracks last
transition time and phase history.

## Subsystem Integration

The service coordinates these subsystems:

| Subsystem | Module | Role |
|-----------|--------|------|
| ClientManager | `bridge/client_manager.py` | Backend connections |
| StartupCoordinator | `bridge/startup_coordinator.py` | 3-phase backend startup orchestration |
| AuthDiscovery | `bridge/auth_discovery.py` | Non-blocking OAuth/OIDC provider discovery |
| ContainerWrapper | `bridge/container/wrapper.py` | Container isolation for stdio backends |
| CapabilityRegistry | `bridge/capability_registry.py` | Capability aggregation |
| AuditLogger | `audit/logger.py` | Audit event recording |
| HealthChecker | `bridge/health/` | Backend health monitoring |
| GroupManager | `bridge/groups.py` | Logical server groups |
| ToolIndex | `bridge/optimizer/` | Tool search index |
| SessionManager | `server/session/` | Client session tracking |
| FeatureFlags | `config/flags.py` | Feature toggles |
| SkillManager | `skills/manager.py` | Skill pack management |
| SecretStore | `secrets/store.py` | Encrypted secret access |
