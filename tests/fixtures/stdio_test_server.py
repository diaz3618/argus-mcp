import logging

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO, format="[StdioTestServer] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

mcp = FastMCP("StdioTest")
logger.info("StdioTest MCP Server instance created.")


@mcp.tool()
async def echo_stdio(message: str) -> str:
    """
    A simple Stdio test tool that echoes back the received message.

    Parameters:
    message (str): The message to echo.

    Returns:
    str: The original message prefixed with "Stdio Echo: ".
    """
    logger.info("Tool 'echo_stdio' called with message: '%s'", message)
    response = f"Stdio Echo: {message}"
    logger.info("Tool 'echo_stdio' responding with: '%s'", response)
    return response


@mcp.tool()
async def add_stdio(a: int, b: int) -> int:
    """
    A simple Stdio test tool that calculates the sum of two integers.

    Parameters:
    a (int): The first integer.
    b (int): The second integer.

    Returns:
    int: The sum of the two integers.
    """
    logger.info("Tool 'add_stdio' called with a=%s, b=%s", a, b)
    result = a + b
    logger.info("Tool 'add_stdio' responding with: %s", result)
    return result


@mcp.resource("x-stdio-test-resource://local/greeting")
def get_stdio_greeting() -> str:
    """
    A simple Stdio test resource that returns a fixed greeting.
    """
    logger.info("Resource 'x-stdio-test-resource://local/greeting' requested.")
    greeting = "Hello from Stdio Test Server Resource!"
    logger.info("Resource 'x-stdio-test-resource://local/greeting' responding with: '%s'", greeting)
    return greeting


if __name__ == "__main__":
    logger.info("Starting StdioTest MCP Server with stdio transport...")

    try:
        mcp.run(transport="stdio")
    except Exception as e:
        logger.exception("StdioTest MCP Server crashed: %s", e)

        import sys

        sys.exit(1)
    logger.info("StdioTest MCP Server has shut down.")
