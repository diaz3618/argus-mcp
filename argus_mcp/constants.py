"""Shared constants for Argus MCP."""

SERVER_NAME = "Argus MCP"
SERVER_VERSION = "0.7.0"

# Network defaults
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000

# SSE transport paths
SSE_PATH = "/sse"
POST_MESSAGES_PATH = "/messages/"

# Streamable HTTP transport path
STREAMABLE_HTTP_PATH = "/mcp"

# Management API
MANAGEMENT_API_PREFIX = "/manage/v1"

# Logging defaults
LOG_DIR = "logs"
DEFAULT_LOG_FILE = "unknown_argus.log"
DEFAULT_LOG_LEVEL = "INFO"

# Backend connection timeouts
SSE_LOCAL_START_DELAY = 5  # seconds to wait for local SSE server startup
MCP_INIT_TIMEOUT = 15  # seconds for MCP session initialization (remote backends only)
CAP_FETCH_TIMEOUT = 10.0  # seconds for capability list fetch
STARTUP_TIMEOUT = 90  # overall per-backend connection timeout (spawn + init) for remote backends
STDIO_MCP_INIT_TIMEOUT = 60  # seconds for MCP session.initialize() after stdio build completes
IMAGE_BUILD_TIMEOUT = 600  # seconds allowed for container image builds (first-run cold builds)

# Staggered startup – limit how many backends connect concurrently to
# avoid resource contention (npm/pip cache lock fights, network
# saturation, CPU spikes).  A small inter-launch delay spreads the
# load further.
STARTUP_CONCURRENCY = 4  # max simultaneous backend initialisations
STARTUP_STAGGER_DELAY = 0.5  # seconds between launching each backend within a batch

# Backend retry defaults
BACKEND_RETRIES = 3  # number of automatic retries for failed backends
BACKEND_RETRY_DELAY = 5.0  # base delay between retries (exponential backoff applied)
BACKEND_RETRY_BACKOFF = 1.5  # multiplier applied to delay on each successive retry

# OAuth auth discovery timeout — how long the retry loop waits for the
# user to complete the browser-based PKCE authentication flow.  Must be
# >= the PKCE flow timeout (600 s) to avoid retries racing ahead of a
# slow interactive login.
AUTH_DISCOVERY_TIMEOUT = 630  # seconds (PKCE 600 s + 30 s buffer)

# SSE heartbeat for management event streams
SSE_HEARTBEAT_INTERVAL = 30  # seconds

# Audit log defaults
AUDIT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB
AUDIT_BACKUP_COUNT = 5

# Graceful shutdown default timeout
SHUTDOWN_TIMEOUT = 30  # seconds

# Reconnect timeout (overall limit for disconnect + connect + rediscover)
RECONNECT_TIMEOUT = 60  # seconds

# Optimizer search default result limit
OPTIMIZER_SEARCH_LIMIT = 5

# Management API input validation limits
MGMT_EVENTS_LIMIT_MIN = 1
MGMT_EVENTS_LIMIT_MAX = 10_000
MGMT_SHUTDOWN_TIMEOUT_MIN = 1
MGMT_SHUTDOWN_TIMEOUT_MAX = 300
MGMT_BACKEND_NAME_MAX_LEN = 255
