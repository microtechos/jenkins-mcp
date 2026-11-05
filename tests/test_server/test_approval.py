import json
import os
import subprocess
import sys

import pytest

SCRIPT = r"""
import asyncio, json, os
from unittest import mock

from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from mcp_jenkins.jenkins import Jenkins
from mcp_jenkins.server import mcp

mode = os.environ['TEST_MODE']  # accept | decline | unchecked | unsupported
tool, args = os.environ['TEST_TOOL'], json.loads(os.environ['TEST_ARGS'])
calls = []
digests = []


def make_fake(name):
    def fake(self, **kwargs):
        calls.append((name, kwargs.get('confirm')))
        digests.append(kwargs.get('context_digest'))
        return {
            'job': 'A/b', 'number': 3, 'queueItem': 5, 'dryRun': not kwargs.get('confirm'),
            'branches': ['*/release/production'], 'parameters': [{'name': 'BRANCH', 'default': 'main'}],
            'downstream': ['02-report'], 'contextDigest': 'digest-1',
        }

    return fake


async def handler(message, response_type, params, context):
    calls.append(('asked', message))
    if mode == 'decline':
        return ElicitResult(action='decline')
    return ElicitResult(action='accept', content={'value': mode == 'accept'})


async def main():
    # 'legacy' pins the handshake protocol era that Claude Code speaks; the newest era has no server-initiated prompts.
    kwargs = {'mode': 'legacy'}
    if mode != 'unsupported':
        kwargs['elicitation_handler'] = handler
    with mock.patch.object(Jenkins, tool, make_fake(tool)):
        async with Client(mcp, **kwargs) as client:
            result = await client.call_tool(tool, args, raise_on_error=False)
    print(json.dumps({'calls': calls, 'digests': digests, 'error': bool(result.is_error)}))


asyncio.run(main())
"""

ENV = {
    'jenkins_url': 'https://jenkins.invalid',
    'jenkins_username': 'u',
    'jenkins_password': 'p',
    'jenkins_allow_trigger': 'true',
    'jenkins_trigger_jobs': 'A/b',
}


def run(mode, tool='trigger_build', args=None, **extra: str):
    arguments = args or {'fullname': 'A/b', 'confirm': True}
    ambient = {key: value for key, value in os.environ.items() if not key.lower().startswith('jenkins_')}
    env = {**ambient, **ENV, 'TEST_MODE': mode, 'TEST_TOOL': tool, 'TEST_ARGS': json.dumps(arguments), **extra}
    command = [sys.executable, '-W', 'ignore', '-c', SCRIPT]
    out = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def starts(result, tool='trigger_build'):
    return [c for c in result['calls'] if c[0] == tool and c[1] is True]


@pytest.mark.parametrize(
    ('tool', 'args'),
    [
        ('trigger_build', {'fullname': 'A/b', 'confirm': True}),
        ('stop_build', {'fullname': 'A/b', 'number': 3, 'confirm': True}),
        ('cancel_queue_item', {'id': 5, 'confirm': True}),
    ],
)
class TestApprovalGate:
    def test_accepted_runs_the_action_after_a_dry_run(self, tool, args):
        result = run('accept', tool, args)

        assert result['error'] is False
        assert [c for c in result['calls'] if c[0] != 'asked'] == [[tool, False], [tool, True]]
        assert any(c[0] == 'asked' for c in result['calls'])

    def test_declined_does_nothing(self, tool, args):
        result = run('decline', tool, args)

        assert result['error'] is True
        assert not starts(result, tool)

    def test_accepting_with_the_box_unchecked_does_nothing(self, tool, args):
        result = run('unchecked', tool, args)

        assert result['error'] is True
        assert not starts(result, tool)

    def test_a_client_that_cannot_ask_is_refused(self, tool, args):
        result = run('unsupported', tool, args)

        assert result['error'] is True
        assert not starts(result, tool)

    def test_the_gate_can_be_switched_off_deliberately(self, tool, args):
        result = run('unsupported', tool, args, jenkins_require_approval='false')

        assert result['error'] is False
        assert len(starts(result, tool)) == 1


def test_a_dry_run_never_asks():
    result = run('accept', args={'fullname': 'A/b'})

    assert result['error'] is False
    assert not any(c[0] == 'asked' for c in result['calls'])
    assert starts(result) == []


def test_the_prompt_shows_what_will_run_and_the_start_is_bound_to_the_dry_run():
    result = run('accept')

    message = next(c[1] for c in result['calls'] if c[0] == 'asked')
    assert 'Branch: */release/production' in message
    assert 'BRANCH=main' in message
    assert 'Then starts: 02-report' in message
    assert result['digests'] == [None, 'digest-1'], 'the confirmed call carries the dry run digest'

