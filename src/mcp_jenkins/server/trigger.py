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


@mcp.tool(tags=['trigger'])
async def stop_build(ctx: Context, fullname: str, number: int, confirm: bool = False) -> dict:  # noqa: FBT001, FBT002
    """Stop one running build of an allowlisted Jenkins job

    Registered together with trigger_build and limited to the same jobs. Dry run by default: call it first,
    show the result, and only call again with confirm=True when the user has said to stop that build.

    Args:
        fullname: The fullname of the job
        number: The number of the running build
        confirm: False (default) = dry run, nothing is stopped; True = stop the build

    Returns:
        job, number, action, building and dryRun
    """
    return jenkins(ctx).stop_build(fullname=fullname, number=number, confirm=confirm)


@mcp.tool(tags=['trigger'])
async def cancel_queue_item(ctx: Context, id: int, confirm: bool = False) -> dict:  # noqa: A002, FBT001, FBT002
    """Cancel one queued build whose job is on the trigger allowlist

    Registered together with trigger_build. The queue item is read first and refused when its job is not
    allowlisted. Dry run by default: call it first, show the result, and only call again with confirm=True
    when the user has said to cancel it.

    Args:
        id: The queue item id (trigger_build returns it as queueItem)
        confirm: False (default) = dry run, nothing is cancelled; True = cancel the queue item

    Returns:
        queueItem, job, action and dryRun
    """
    return jenkins(ctx).cancel_queue_item(id=id, confirm=confirm)
