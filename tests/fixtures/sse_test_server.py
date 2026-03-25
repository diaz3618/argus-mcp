# tests/fixtures/sse_test_server.py
import asyncio
import logging
import signal
import sys
from typing import Optional

import uvicorn
from mcp import types as mcp_types
from mcp.server import Server as McpLowLevelServer
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="[SseTestServer] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create a FastMCP server instance named "SseTest"
mcp = FastMCP("SseTest")
logger.info("SseTest MCP Server (FastMCP) instance created.")

SSE_SERVER_HOST = "127.0.0.1"
SSE_SERVER_PORT = 8021
SSE_ENDPOINT_PATH = "/mcp_sse"
SSE_POST_MESSAGES_PATH = "/mcp_messages/"


@mcp.tool()
async def echo_sse(message: str, repeat: int = 1) -> str:
    """
    A simple SSE test tool that echoes back the received message, optionally repeated.

    Parameters:
    message (str): The message to echo.
    repeat (int): Number of times to repeat the message, defaults to 1.

    Returns:
    str: The original message (possibly repeated) prefixed with "SSE Echo: ".
    """
    logger.info("Tool 'echo_sse' called with message: '%s', repeat: %s", message, repeat)
    response_message = f"SSE Echo: {message} " * repeat
    response = response_message.strip()
    logger.info("Tool 'echo_sse' responding with: '%s'", response)
    return response


@mcp.prompt()
def sse_example_prompt(user_name: str) -> list[mcp_types.PromptMessage]:
    """
    A simple SSE test prompt.

    Parameters:
    user_name (str): The user's name.

    Returns:
    list[mcp_types.PromptMessage]: A list of user and assistant messages.
    """
    logger.info("Prompt 'sse_example_prompt' called with user_name: '%s'", user_name)
    return [
        mcp_types.PromptMessage(
            role="user",
            content=mcp_types.TextContent(type="text", text=f"Hello, my name is {user_name}."),
        ),
        mcp_types.PromptMessage(
            role="assistant",
            content=mcp_types.TextContent(
                type="text",
                text=f"Nice to meet you, {user_name}! How can I help you today via SSE?",
            ),
        ),
    ]


if not isinstance(mcp._mcp_server, McpLowLevelServer):
    logger.error("FastMCP instance did not initialize its internal McpServer correctly.")
    raise TypeError("mcp._mcp_server is not of type McpLowLevelServer")
mcp_low_level_server: McpLowLevelServer = mcp._mcp_server

sse_transport = SseServerTransport(SSE_POST_MESSAGES_PATH)
logger.info("SseServerTransport created for POST messages at %s", SSE_POST_MESSAGES_PATH)


async def handle_sse_connection(request: Request) -> None:
    """Handle incoming SSE connection requests (GET requests)."""
    client_host = request.client.host if request.client else "unknown"
    client_port = request.client.port if request.client else 0
    logger.info(
        "New SSE connection request from %s:%s to %s",
        client_host,
        client_port,
        request.url.path,
    )
    async with sse_transport.connect_sse(
        request.scope,
        request.receive,
        request._send,
    ) as (read_stream, write_stream):
        logger.debug("SSE streams established. Starting MCP protocol run.")

        try:
            server_capabilities = mcp_low_level_server.get_capabilities(
                notification_options=NotificationOptions(), experimental_capabilities={}
            )
            logger.debug("Capabilities for SseTestServer: %s", server_capabilities)

            init_options = InitializationOptions(
                server_name="SseTestServer",
                server_version="1.0.1",
                capabilities=server_capabilities,
            )
            logger.debug("MCP InitializationOptions for SSE connection: %s", init_options)

            await mcp_low_level_server.run(read_stream, write_stream, init_options)
        except Exception as e:
            logger.exception("Error during MCP run for SSE connection: %s", e)

    logger.info("SSE connection from %s:%s closed.", client_host, client_port)


sse_app = Starlette(
    debug=False,
    routes=[
        Route(SSE_ENDPOINT_PATH, endpoint=handle_sse_connection),
        Mount(SSE_POST_MESSAGES_PATH, app=sse_transport.handle_post_message),
    ],
    on_startup=[
        lambda: logger.info(
            "SseTestServer Starlette app starting up. SSE GET on http://%s:%s%s",
            SSE_SERVER_HOST,
            SSE_SERVER_PORT,
            SSE_ENDPOINT_PATH,
        )
    ],
    on_shutdown=[lambda: logger.info("SseTestServer Starlette app shutting down.")],
)

uvicorn_server_instance: Optional[uvicorn.Server] = None


def signal_handler(sig, frame):
    logger.warning("Received signal %s. Initiating graceful shutdown for SseTestServer...", sig)
    if uvicorn_server_instance:
        uvicorn_server_instance.should_exit = True
    else:
        logger.error("Uvicorn server instance not found for signal handling. Exiting.")
        sys.exit(1)


async def main_async():
    global uvicorn_server_instance

    config = uvicorn.Config(
        app=sse_app,
        host=SSE_SERVER_HOST,
        port=SSE_SERVER_PORT,
        log_level="info",
    )
    uvicorn_server_instance = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_name, signal_handler, sig_name, None)
            logger.info("Registered signal handler for %s", sig_name.name)
        except NotImplementedError:
            signal.signal(sig_name, signal_handler)
            logger.warning(
                "Registered signal.signal handler for %s (Windows fallback)",
                sig_name.name,
            )

    logger.info(
        "Starting SseTest MCP Server (uvicorn.Server) on http://%s:%s",
        SSE_SERVER_HOST,
        SSE_SERVER_PORT,
    )

    try:
        await uvicorn_server_instance.serve()
    except KeyboardInterrupt:
        logger.info(
            "KeyboardInterrupt caught in main_async. Server should be shutting down via signal handler."
        )
    except Exception as e:
        logger.exception("SseTest MCP Server (uvicorn.Server) crashed: %s", e)
    finally:
        logger.info("SseTest MCP Server (uvicorn.Server) has shut down or is shutting down.")


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("SseTestServer main execution interrupted by KeyboardInterrupt. Exiting.")
    except SystemExit as e:
        logger.info("SseTestServer exiting with code %s.", e.code)
    finally:
        logger.info("SseTestServer application finished.")
