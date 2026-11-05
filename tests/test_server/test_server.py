import json
import os
import subprocess
import sys

WRITE_TOOLS = {
    'build_item',
    'stop_build',
    'cancel_queue_item',
    'submit_input',
    'set_item_config',
    'set_node_config',
    'run_groovy_script',
    'get_node_config',
    'trigger_build',
}

LISTING = (
    'import asyncio, json; from mcp_jenkins.server import mcp; '
    'tools = asyncio.run(mcp.list_tools()); '
    'print(json.dumps({t.name: sorted(t.tags or []) for t in tools}))'
)


def _tools_with_a_clean_environment() -> dict:
    """List the tools of a fresh server started with no JENKINS_* variables, whatever this machine exports."""
    env = {key: value for key, value in os.environ.items() if not key.lower().startswith('jenkins_')}
    out = subprocess.run(  # noqa: S603
        [sys.executable, '-W', 'ignore', '-c', LISTING], env=env, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_server_exposes_only_read_tools_by_default():
    tools = _tools_with_a_clean_environment()

    assert not set(tools) & WRITE_TOOLS
    assert 'list_builds' in tools
    assert 'get_jobs_status' in tools
    assert all(tags == ['read'] for tags in tools.values())


def test_server_has_no_http_routes():
    from mcp_jenkins.server import mcp

    assert not hasattr(mcp, 'http_app') or not any(
        getattr(route, 'path', None) == '/healthz' for route in mcp.http_app(transport='http').routes
    )
