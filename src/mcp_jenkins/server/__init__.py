from fastmcp import FastMCP

from mcp_jenkins.core import LifespanContext, lifespan

__all__ = ['mcp']

mcp = FastMCP[LifespanContext]('mcp-jenkins', lifespan=lifespan)

# Import tool modules to register them with the MCP server
# This must happen after mcp is created so the @mcp.tool() decorators can reference it
from mcp_jenkins.server import build, item, node, plugin, queue, view  # noqa: F401, E402
