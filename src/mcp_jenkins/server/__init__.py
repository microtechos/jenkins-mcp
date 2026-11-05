import os

from fastmcp import FastMCP

from mcp_jenkins.core import LifespanContext, lifespan

__all__ = ['mcp']

mcp = FastMCP[LifespanContext]('mcp-jenkins', lifespan=lifespan)

# Import tool modules to register them with the MCP server
# This must happen after mcp is created so the @mcp.tool() decorators can reference it
from mcp_jenkins.server import build, item, node, plugin, queue, view  # noqa: F401, E402

# The one write tool exists only when the server was started with --allow-trigger.
if os.environ.get('jenkins_allow_trigger', 'false').lower() == 'true':
    from mcp_jenkins.server import trigger  # noqa: F401
