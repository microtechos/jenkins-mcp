import pytest

from mcp_jenkins.server import mcp

WRITE_TOOLS = {
    'build_item',
    'stop_build',
    'cancel_queue_item',
    'submit_input',
    'set_item_config',
    'set_node_config',
    'run_groovy_script',
    'get_node_config',
}


@pytest.mark.asyncio
async def test_server_exposes_only_read_tools():
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert not names & WRITE_TOOLS
    assert 'list_builds' in names
    assert all('read' in (tool.tags or set()) for tool in tools)


def test_server_has_no_http_routes():
    assert not hasattr(mcp, 'http_app') or not any(
        getattr(route, 'path', None) == '/healthz' for route in mcp.http_app(transport='http').routes
    )
