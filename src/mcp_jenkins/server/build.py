import base64

from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.jenkins import Jenkins
from mcp_jenkins.jenkins.redact import redact_data, redact_params, redact_text
from mcp_jenkins.server import mcp


def _resolve_build_number(client: Jenkins, fullname: str, number: int | None) -> int:
    """Resolve an omitted build number to the job's last build, raising a clear error when it has none

    The number is fetched with a tree query rather than a depth=1 item fetch: the latter returns every
    build stub, action and parameter definition of the job to read a single integer.
    """
    if number is not None:
        return number

    number = client.get_last_build_number(fullname=fullname)
    if number is None:
        raise ValueError(f'No build found for job: {fullname}')

    return number


@mcp.tool(tags=['read'])
async def get_running_builds(ctx: Context) -> list[dict]:
    """Get all running builds from Jenkins

    Returns:
        A list of all running builds
    """
    return [
        item.model_dump(include={'number', 'url', 'building', 'timestamp'})
        for item in jenkins(ctx).get_running_builds()
    ]


@mcp.tool(tags=['read'])
async def list_builds(ctx: Context, fullname: str, limit: int = 20) -> list[dict]:
    """List the most recent builds of a job in Jenkins, newest first

    Args:
        fullname: The fullname of the job
        limit: How many builds to return, 1-100 (default 20)

    Returns:
        A list of builds with number, url, result, building, timestamp and duration
    """
    return jenkins(ctx).get_builds(fullname=fullname, limit=limit)


@mcp.tool(tags=['read'])
async def get_build(ctx: Context, fullname: str, number: int | None = None) -> dict:
    """Get specific build info from Jenkins

    Args:
        fullname: The fullname of the job
        number: The number of the build, if None, get the last build

    Returns:
        The build info
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)

    return jenkins(ctx).get_build(fullname=fullname, number=number).model_dump(exclude_none=True)


@mcp.tool(tags=['read'])
async def get_build_scripts(ctx: Context, fullname: str, number: int | None = None) -> list[str]:
    """Get the scripts used in a specific build in Jenkins

    Args:
        fullname: The fullname of the job
        number: The number of the build, if None, get the last build

    Returns:
        A list of scripts used in the build
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)

    return [redact_text(script) for script in jenkins(ctx).get_build_replay(fullname=fullname, number=number).scripts]


@mcp.tool(tags=['read'])
async def get_build_console_output(
    ctx: Context,
    fullname: str,
    number: int | None = None,
    pattern: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> str:
    """Get the console output of a specific build in Jenkins

    Args:
        fullname: The fullname of the job
        number: The number of the build, if None, get the last build
        pattern: Optional regex pattern to filter lines (only matching lines are returned)
        offset: Number of lines to skip from the beginning after filtering, default 0
        limit: Maximum number of lines to return after filtering and offset

    Returns:
        The console output of the build
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)

    return jenkins(ctx).get_build_console_output(
        fullname=fullname, number=number, pattern=pattern, offset=offset, limit=limit
    )


@mcp.tool(tags=['read'])
async def get_build_test_report(ctx: Context, fullname: str, number: int | None = None) -> dict:
    """Get the test report of a specific build in Jenkins

    The report lists every test case, passing ones included, so it can be very large; use
    get_build_test_failures to see what failed.

    Args:
        fullname: The fullname of the job
        number: The number of the build, if None, get the last build

    Returns:
        The test report of the build
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)

    return redact_data(jenkins(ctx).get_build_test_report(fullname=fullname, number=number))


@mcp.tool(tags=['read'])
async def get_build_test_failures(
    ctx: Context,
    fullname: str,
    number: int | None = None,
    limit: int | None = 50,
    max_stack_trace_length: int = 2000,
) -> dict:
    """Get the failing tests of a specific build in Jenkins, with their error details

    For a matrix build, the failures of all configurations are returned, each with the URL of its
    configuration build.

    Args:
        fullname: The fullname of the job
        number: The number of the build, if None, get the last build
        limit: Maximum number of failures to return, 1-200 (None means 200)
        max_stack_trace_length: Stack traces longer than this are cut to this many characters

    Returns:
        The test counts of the build, its failures and whether the failures were truncated to the limit
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)
    limit = 200 if limit is None else max(1, min(limit, 200))

    return redact_data(
        jenkins(ctx).get_build_test_failures(
            fullname=fullname,
            number=number,
            limit=limit,
            max_stack_trace_length=max_stack_trace_length,
        )
    )


@mcp.tool(tags=['read'])
async def get_build_parameters(ctx: Context, fullname: str, number: int | None = None) -> dict:
    """Get the parameters of a specific build in Jenkins

    Args:
        fullname: The fullname of the job
        number: The number of the build, if None, get the last build

    Returns:
        A dictionary of build parameter names and their values
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)

    return redact_params(jenkins(ctx).get_build_parameters(fullname=fullname, number=number))


@mcp.tool(tags=['read'])
async def get_pending_inputs(ctx: Context, fullname: str, number: int | None = None) -> list[dict]:
    """Get the pending input steps of a specific build in Jenkins

    A pipeline showing "Paused for Input" is waiting on an input step. This lists the input id and the
    parameter definitions the pipeline is waiting for.

    Only the given build is inspected. With number=None that is the job's last build, so a paused build
    that is no longer the most recent one is not found that way — locate it with get_running_builds and
    pass its number explicitly.

    Args:
        fullname: The fullname of the job
        number: The number of the build, if None, check the last build

    Returns:
        A list of pending inputs with id, message, proceedText and inputs (parameter definitions)
    """
    client = jenkins(ctx)

    number = _resolve_build_number(client, fullname, number)

    return [
        redact_data(pending_input.model_dump(exclude_none=True))
        for pending_input in client.get_build_pending_inputs(fullname=fullname, number=number)
    ]


@mcp.tool(tags=['read'])
async def get_all_build_artifacts(ctx: Context, fullname: str, number: int | None = None) -> list[dict]:
    """List the artifacts of a specific build in Jenkins

    Args:
        fullname: The fullname of the job
        number: The number of the build, if None, get the last build

    Returns:
        A list of artifact metadata dicts with fileName, relativePath, and displayPath
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)

    return [
        artifact.model_dump(exclude_none=True)
        for artifact in jenkins(ctx).get_build_artifacts(fullname=fullname, number=number)
    ]


@mcp.tool(tags=['read'])
async def get_build_artifact(ctx: Context, fullname: str, relative_path: str, number: int | None = None) -> dict:
    """Download an artifact from a specific build in Jenkins

    Binary files are returned as base64-encoded content; text files are returned as plain text.

    Args:
        fullname: The fullname of the job
        relative_path: The relative path of the artifact (e.g. playwright-report/index.html)
        number: The number of the build, if None, get the last build

    Returns:
        A dict with 'content' (str) and 'encoding' ('utf-8' or 'base64')
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)

    content = jenkins(ctx).get_build_artifact(fullname=fullname, number=number, relative_path=relative_path)

    try:
        return {'content': content.decode('utf-8'), 'encoding': 'utf-8'}
    except UnicodeDecodeError:
        return {'content': base64.b64encode(content).decode('ascii'), 'encoding': 'base64'}


@mcp.tool(tags=['read'])
async def get_build_artifact_url(ctx: Context, fullname: str, relative_path: str, number: int | None = None) -> str:
    """Get the direct URL of an artifact from a specific build in Jenkins

    Args:
        fullname: The fullname of the job
        relative_path: The relative path of the artifact (e.g. playwright-report/index.html)
        number: The number of the build, if None, get the last build

    Returns:
        The direct Jenkins URL of the artifact
    """
    number = _resolve_build_number(jenkins(ctx), fullname, number)

    return jenkins(ctx).get_build_artifact_url(fullname=fullname, number=number, relative_path=relative_path)
