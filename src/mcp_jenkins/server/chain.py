import asyncio
import time

from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.jenkins.chain import TERMINAL, chain_status
from mcp_jenkins.server import mcp

MAX_WAIT_SECONDS = 50
POLL_SECONDS = 5


@mcp.tool(tags=['read'])
async def get_chain_status(
    ctx: Context,
    entry: str,
    entry_number: int | None = None,
    chain: list[str] | None = None,
    wait_seconds: int = 0,
) -> dict:
    """Say where a release chain stands: passed all the way, stopped at a job, or still running

    Follows one build of the entry job through the downstream jobs you expect after it. One call replaces
    list_builds on every job. Read-only. A downstream build is matched to the entry build by its upstream cause;
    when builds carry no cause information the oldest build started after the entry build is used, and
    `attribution` says which was used.

    With wait_seconds the call waits (checking every 5 s) until the chain has finished, passed or stopped, or the
    time is up, so a monitor can call it repeatedly instead of polling many tools. Call again while the verdict
    is running or waiting.

    Args:
        entry: Fullname of the entry job (the job that was started)
        entry_number: The entry build to follow; omit for the latest build of the entry job
        chain: Ordered fullnames of the downstream jobs expected after the entry job, for example `jenkinsChain`
            of `mtrelease trains --json`. Omit to follow the entry job alone
        wait_seconds: 0-50, how long to wait for the chain to finish (default 0 = answer now)

    Returns:
        verdict (passed, failed, aborted, running or waiting), stoppedAt, runningAt, finalJob, attribution,
        rows (job, number, state, durationMs) and a one-line summary
    """
    client = jenkins(ctx)
    wait = max(0, min(int(wait_seconds), MAX_WAIT_SECONDS))
    deadline = time.monotonic() + wait

    while True:
        status = chain_status(client, entry=entry, entry_number=entry_number, chain=chain)
        # Follow the same build on every poll, even when a newer entry build starts meanwhile.
        entry_number = status['rows'][0]['number']
        if status['verdict'] in TERMINAL or time.monotonic() + POLL_SECONDS > deadline:
            return status
        await asyncio.sleep(POLL_SECONDS)
