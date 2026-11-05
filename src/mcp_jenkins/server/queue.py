from fastmcp import Context

from mcp_jenkins.core.lifespan import jenkins
from mcp_jenkins.server import mcp


@mcp.tool(tags=['read'])
async def get_all_queue_items(ctx: Context) -> list[dict]:
    """Get all items in Jenkins queue, each with the job it belongs to (name and url)

    Returns:
        A list of all items in the Jenkins queue
    """
    rows = []
    for item in jenkins(ctx).get_queue().items:
        row = item.model_dump(exclude_none=True, exclude={'task'})
        if item.task.name:
            row['name'] = item.task.name
        if item.task.url:
            row['job'] = item.task.url
        rows.append(row)
    return rows


@mcp.tool(tags=['read'])
async def get_queue_item(ctx: Context, id: int) -> dict:
    """Get a specific item in Jenkins queue by id

    Args:
        id: The id of the queue item

    Returns:
        The queue item
    """
    item = jenkins(ctx).get_queue_item(id=id, depth=1)
    return item.model_dump(exclude_none=True)

