from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.server import mcp


@mcp.tool(tags=['trigger'])
async def trigger_build(ctx: Context, fullname: str, confirm: bool = False) -> dict:  # noqa: FBT001, FBT002
    """Start a build of one allowlisted Jenkins job

    Only registered when the server was started with --allow-trigger, and only for the exact jobs in
    --trigger-jobs. A dry run is the default: call it first, show the result to the user, and only call
    again with confirm=True when the user has said to start that job. A parameterised job is started with
    its default parameter values. Starting a job may deploy to production.

    Args:
        fullname: The fullname of the job
        confirm: False (default) = dry run, nothing is started; True = start the build

    Returns:
        job, action, parameterised, dryRun and, after a real start, queueItem and queueUrl
    """
    return jenkins(ctx).trigger_build(fullname=fullname, confirm=confirm)
