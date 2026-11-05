import xml.etree.ElementTree as ET

from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.jenkins.compact import (
    DEFAULT_LIMIT,
    compact_items,
    compact_rows,
    summarize_config,
)
from mcp_jenkins.jenkins.redact import redact_config_xml
from mcp_jenkins.server import mcp


@mcp.tool(tags=['read'])
async def get_all_items(ctx: Context, fields: list[str] | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Get all items from Jenkins, compact: prefer query_items with a filter on a large instance

    Args:
        fields: Fields to return, from fullname, name, kind, class_, url, color (default: fullname, kind, color)
        limit: Maximum number of items, 1-1000 (default 200); a final row says how many were dropped

    Returns:
        A list of items
    """
    return compact_items(jenkins(ctx).get_items(), fields=fields, limit=limit)


@mcp.tool(tags=['read'])
async def get_item(ctx: Context, fullname: str) -> dict:
    """Get specific item from Jenkins

    Args:
        fullname: The fullname of the item

    Returns:
        The item
    """
    return jenkins(ctx).get_item(fullname=fullname).model_dump(exclude_none=True)


@mcp.tool(tags=['read'])
async def get_item_config(ctx: Context, fullname: str) -> str:
    """Get specific item config from Jenkins

    Secret-looking values (encrypted secrets, password/token elements, inline NAME=value assignments for
    password/token/secret/key variables) are replaced with [REDACTED]. Credential ids are kept.

    Args:
        fullname: The fullname of the item

    Returns:
        The config of the item, with secrets redacted
    """
    return redact_config_xml(jenkins(ctx).get_item_config(fullname=fullname))


@mcp.tool(tags=['read'])
async def query_items(
    ctx: Context,
    class_pattern: str | None = None,
    fullname_pattern: str | None = None,
    color_pattern: str | None = None,
    folder_depth: int | None = None,
    fields: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Query items from Jenkins, compact

    Args:
        class_pattern: The pattern of the _class
        fullname_pattern: The pattern of the fullname
        color_pattern: The pattern of the color
        folder_depth: The maximum depth of folders to traverse. If None, traverses all levels.
        fields: Fields to return, from fullname, name, kind, class_, url, color (default: fullname, kind, color)
        limit: Maximum number of items, 1-1000 (default 200); a final row says how many were dropped

    Returns:
        A list of items
    """
    return compact_items(
        jenkins(ctx).query_items(
            class_pattern=class_pattern,
            fullname_pattern=fullname_pattern,
            color_pattern=color_pattern,
            folder_depth=folder_depth,
        ),
        fields=fields,
        limit=limit,
    )


@mcp.tool(tags=['read'])
async def get_jobs_status(
    ctx: Context,
    fullname_pattern: str | None = None,
    folder_depth: int | None = 3,
    limit: int = 100,
) -> list[dict]:
    """Last build of every job matching a pattern, in one call (use this instead of list_builds per job)

    Args:
        fullname_pattern: Regex searched in the job full name, e.g. "^Branch-Retail/prod-branch-retail-cloud/"
        folder_depth: The maximum depth of folders to traverse (default 3)
        limit: Maximum number of jobs, 1-1000 (default 100)

    Returns:
        One row per job: job, color, build, result, building, durationS, timestamp (epoch ms)
    """
    rows = jenkins(ctx).get_jobs_status(fullname_pattern=fullname_pattern, folder_depth=folder_depth)
    return compact_rows(rows, limit=limit)


@mcp.tool(tags=['read'])
async def get_item_summary(ctx: Context, fullname: str) -> dict:
    """Summarise a job's configuration: repo and branch, steps, triggers, parameters, downstream jobs

    A fraction of get_item_config. Secret-looking values are redacted, credential ids and long scripts are
    not reproduced. Use get_item_config only when you need the exact XML.

    Args:
        fullname: The fullname of the item

    Returns:
        kind, disabled, scm (urls, branches), steps (phase, type, command clipped), triggers, parameters,
        downstream, wrappers
    """
    return summarize_config(jenkins(ctx).get_item_config(fullname=fullname))


@mcp.tool(tags=['read'])
async def get_item_parameters(ctx: Context, fullname: str) -> list[dict]:
    """Get the parameter definitions of a Jenkins job

    Args:
        fullname: The fullname of the item

    Returns:
        A list of parameter definitions, each containing name, type, defaultValue, and description
    """
    config_xml = jenkins(ctx).get_item_config(fullname=fullname)
    root = ET.fromstring(config_xml)

    params = []
    for param in root.iter('parameterDefinitions'):
        for definition in param:
            entry = {
                'name': definition.findtext('name', ''),
                'type': definition.tag,
                'defaultValue': definition.findtext('defaultValue', ''),
                'description': definition.findtext('description', ''),
            }
            params.append(entry)

    return params
