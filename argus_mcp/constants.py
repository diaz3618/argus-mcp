"""Shared constants for Argus MCP."""

SERVER_NAME = "Argus MCP"
SERVER_VERSION = "0.6.1"

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
MCP_INIT_TIMEOUT = 15  # seconds for MCP session initialization
CAP_FETCH_TIMEOUT = 10.0  # seconds for capability list fetch
STARTUP_TIMEOUT = 120  # overall per-backend connection timeout (spawn + init)

# Backend retry defaults
BACKEND_RETRIES = 1  # number of automatic retries for failed backends
BACKEND_RETRY_DELAY = 5.0  # seconds to wait between retries
