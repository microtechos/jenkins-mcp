from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.server import mcp
from mcp_jenkins.server.approval import require_approval, start_message


@mcp.tool(tags=['trigger'])
async def trigger_build(ctx: Context, fullname: str, confirm: bool = False) -> dict:  # noqa: FBT001, FBT002
    """Start a build of one allowlisted Jenkins job

    Only registered when the server was started with --allow-trigger, and only for the exact jobs in
    --trigger-jobs. A dry run is the default: call it first, show the result to the user (it lists the branch,
    default parameters and downstream jobs), and only call again with confirm=True when the user has said to
    start that job. A confirmed start also asks the user for approval through the client, showing the branch,
    parameters and downstream jobs, and is refused if the job changed after the dry run. A parameterised job is
    started with its default parameter values. Starting a job may deploy to production.

    Args:
        fullname: The fullname of the job
        confirm: False (default) = dry run, nothing is started; True = start the build

    Returns:
        job, action, parameterised, dryRun, branches, parameters, downstream, contextDigest and, after a real
        start, queueItem and queueUrl
    """
    client = jenkins(ctx)
    plan = client.trigger_build(fullname=fullname, confirm=False)
    if not confirm:
        return plan

    await require_approval(ctx, start_message(plan))
    return client.trigger_build(fullname=fullname, confirm=True, context_digest=plan.get('contextDigest'))


@mcp.tool(tags=['trigger'])
async def stop_build(ctx: Context, fullname: str, number: int, confirm: bool = False) -> dict:  # noqa: FBT001, FBT002
    """Stop one running build of an allowlisted Jenkins job

    Registered together with trigger_build; allowed on the trigger jobs and on the stop-only jobs (for example
    the rest of a release chain). Dry run by default: call it first, show the result, and only call again with
    confirm=True when the user has said to stop that build. A confirmed stop also asks the user for approval.

    Args:
        fullname: The fullname of the job
        number: The number of the running build
        confirm: False (default) = dry run, nothing is stopped; True = stop the build

    Returns:
        job, number, action, building and dryRun
    """
    client = jenkins(ctx)
    plan = client.stop_build(fullname=fullname, number=number, confirm=False)
    if not confirm:
        return plan

    await require_approval(ctx, f'Stop build #{plan["number"]} of {plan["job"]}?')
    return client.stop_build(fullname=fullname, number=number, confirm=True)


@mcp.tool(tags=['trigger'])
async def cancel_queue_item(ctx: Context, id: int, confirm: bool = False) -> dict:  # noqa: A002, FBT001, FBT002
    """Cancel one queued build whose job is on the trigger or stop allowlist

    Registered together with trigger_build. The queue item is read first and refused when its job is not
    allowlisted. Dry run by default: call it first, show the result, and only call again with confirm=True
    when the user has said to cancel it. A confirmed cancel also asks the user for approval.

    Args:
        id: The queue item id (trigger_build returns it as queueItem)
        confirm: False (default) = dry run, nothing is cancelled; True = cancel the queue item

    Returns:
        queueItem, job, action and dryRun
    """
    client = jenkins(ctx)
    plan = client.cancel_queue_item(id=id, confirm=False)
    if not confirm:
        return plan

    await require_approval(ctx, f'Cancel queued build {plan["queueItem"]} of {plan["job"]}?')
    return client.cancel_queue_item(id=id, confirm=True)
