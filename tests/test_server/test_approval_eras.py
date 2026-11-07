"""Approval prompt per MCP protocol era.

Claude Code 2.1.318 connected to this server on the modern era (2026-07-28) and a confirmed start failed with
"This client cannot ask you to approve the action": FastMCP's `ctx.elicit` refuses there, because that era has no
server-initiated requests. On it the server now asks with an InputRequiredResult and the client retries the call
with the answer. These tests drive the same server with a client that can (or can not) answer, once per era.
"""

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

era = os.environ['TEST_ERA']  # legacy | 2026-07-28
mode = os.environ['TEST_MODE']  # accept | decline | unchecked | unsupported | changed
tool, args = os.environ['TEST_TOOL'], json.loads(os.environ['TEST_ARGS'])
calls = []
dry_runs = []


def make_fake(name):
    def fake(self, **kwargs):
        confirm = kwargs.get('confirm')
        calls.append((name, confirm))
        if not confirm:
            dry_runs.append(1)
        # 'changed': the job configuration differs by the time the client retries with its answer
        digest = 'digest-2' if mode == 'changed' and len(dry_runs) > 1 else 'digest-1'
        return {
            'job': 'A/b', 'number': 3, 'queueItem': 5, 'dryRun': not confirm,
            'branches': ['*/release/production'], 'parameters': [], 'downstream': [], 'contextDigest': digest,
        }

    return fake


async def handler(message, response_type, params, context):
    calls.append(('asked', message))
    if mode == 'decline':
        return ElicitResult(action='decline')
    return ElicitResult(action='accept', content={'value': mode != 'unchecked'})


async def main():
    kwargs = {'mode': era}
    if mode != 'unsupported':
        kwargs['elicitation_handler'] = handler
    with mock.patch.object(Jenkins, tool, make_fake(tool)):
        async with Client(mcp, **kwargs) as client:
            try:
                result = await client.call_tool(tool, args, raise_on_error=False)
                error, text = bool(result.is_error), ' '.join(getattr(c, 'text', '') for c in result.content)
            except Exception as e:  # a modern client without a handler refuses to answer, before any retry
                error, text = True, f'client error: {e}'
    print(json.dumps({'calls': calls, 'error': error, 'text': text}))


asyncio.run(main())
"""

ENV = {
    'jenkins_url': 'https://jenkins.invalid',
    'jenkins_username': 'u',
    'jenkins_password': 'p',
    'jenkins_allow_trigger': 'true',
    'jenkins_trigger_jobs': 'A/b',
}

TOOLS = [
    ('trigger_build', {'fullname': 'A/b', 'confirm': True}),
    ('stop_build', {'fullname': 'A/b', 'number': 3, 'confirm': True}),
    ('cancel_queue_item', {'id': 5, 'confirm': True}),
]
ERAS = ['legacy', '2026-07-28']


def run(era, mode, tool='trigger_build', args=None, **extra: str):
    arguments = args or {'fullname': 'A/b', 'confirm': True}
    ambient = {key: value for key, value in os.environ.items() if not key.lower().startswith('jenkins_')}
    env = {
        **ambient,
        **ENV,
        'TEST_ERA': era,
        'TEST_MODE': mode,
        'TEST_TOOL': tool,
        'TEST_ARGS': json.dumps(arguments),
        **extra,
    }
    out = subprocess.run(  # noqa: S603
        [sys.executable, '-W', 'ignore', '-c', SCRIPT], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def acted(result, tool='trigger_build'):
    return [c for c in result['calls'] if c[0] == tool and c[1] is True]


def asked(result):
    return [c for c in result['calls'] if c[0] == 'asked']


@pytest.mark.parametrize('era', ERAS)
@pytest.mark.parametrize(('tool', 'args'), TOOLS)
class TestApprovalPerEra:
    def test_accept_shows_the_prompt_and_runs_the_action(self, era, tool, args):
        result = run(era, 'accept', tool, args)

        assert len(asked(result)) == 1, f'no prompt on {era}: {result["text"]}'
        assert result['error'] is False, result['text']
        assert len(acted(result, tool)) == 1

    def test_decline_shows_the_prompt_and_does_nothing(self, era, tool, args):
        result = run(era, 'decline', tool, args)

        assert len(asked(result)) == 1, f'no prompt on {era}: {result["text"]}'
        assert result['error'] is True
        assert not acted(result, tool)

    def test_accepting_with_the_box_unchecked_does_nothing(self, era, tool, args):
        result = run(era, 'unchecked', tool, args)

        assert result['error'] is True
        assert not acted(result, tool)

    def test_a_client_that_cannot_answer_does_nothing(self, era, tool, args):
        result = run(era, 'unsupported', tool, args)

        assert result['error'] is True
        assert not acted(result, tool)

    def test_the_gate_can_be_switched_off_deliberately(self, era, tool, args):
        result = run(era, 'unsupported', tool, args, jenkins_require_approval='false')

        assert result['error'] is False
        assert len(acted(result, tool)) == 1
        assert not asked(result)

    def test_a_dry_run_never_asks(self, era, tool, args):
        result = run(era, 'accept', tool, {**args, 'confirm': False})

        assert result['error'] is False
        assert not asked(result)
        assert not acted(result, tool)


def test_modern_start_is_refused_when_the_job_changed_after_the_prompt():
    result = run('2026-07-28', 'changed')

    assert len(asked(result)) == 1
    assert result['error'] is True
    assert 'changed after the approval prompt' in result['text']
    assert not acted(result)


def test_modern_prompt_shows_the_same_details_as_the_classic_one():
    classic = run('legacy', 'accept')
    modern = run('2026-07-28', 'accept')

    assert asked(classic)[0][1] == asked(modern)[0][1]
