import os
import subprocess
import sys

import pytest

from mcp_jenkins.jenkins import Jenkins

ALLOWED = 'Branch-Retail/cloud/01-common,Branch-Retail/cloud/web-a'


@pytest.fixture(autouse=True)
def mock_session(mocker):
    session = mocker.Mock()
    mocker.patch('mcp_jenkins.jenkins.rest_client.requests.Session', autospec=True, return_value=session)
    return session


def make(mocker, **kwargs: object):
    mocker.patch.object(Jenkins, 'crumb_header', new_callable=mocker.PropertyMock, return_value={})
    return Jenkins(url='https://example.com/', username='u', password='p', **kwargs)


def respond(mocker, session, *, buildable=True, parameterised=False, location=''):
    info = {'buildable': buildable, 'property': [{'parameterDefinitions': [{'name': 'X'}]}] if parameterised else []}
    session.request.side_effect = lambda **kw: (
        mocker.Mock(json=lambda: info)
        if kw['method'] == 'GET'
        else mocker.Mock(headers={'Location': location} if location else {})
    )


def posts(session):
    return [c.kwargs for c in session.request.call_args_list if c.kwargs['method'] == 'POST']


def test_disabled_by_default(mocker, mock_session):
    with pytest.raises(PermissionError, match='disabled'):
        make(mocker, trigger_jobs=ALLOWED).trigger_build(fullname='Branch-Retail/cloud/web-a', confirm=True)

    assert mock_session.request.call_count == 0


def test_enabled_without_a_list_allows_nothing(mocker, mock_session):
    with pytest.raises(PermissionError, match='not in the trigger allowlist'):
        make(mocker, allow_trigger=True).trigger_build(fullname='Branch-Retail/cloud/web-a', confirm=True)

    assert mock_session.request.call_count == 0


@pytest.mark.parametrize(
    'fullname',
    ['Branch-Retail/cloud', 'Branch-Retail/cloud/web-b', 'Branch-Retail/cloud/web-a/extra', 'Branch-Restaurant/x', ''],
)
def test_job_outside_the_list_is_refused(mocker, mock_session, fullname):
    with pytest.raises(PermissionError, match='not in the trigger allowlist'):
        make(mocker, allow_trigger=True, trigger_jobs=ALLOWED).trigger_build(fullname=fullname, confirm=True)

    assert mock_session.request.call_count == 0


def test_traversal_in_an_allowed_looking_name_is_refused(mocker, mock_session):
    jenkins = make(mocker, allow_trigger=True, trigger_jobs='A/../B')

    with pytest.raises(ValueError, match='Invalid job fullname'):
        jenkins.trigger_build(fullname='A/../B', confirm=True)

    assert not posts(mock_session)


def test_dry_run_is_the_default_and_sends_no_post(mocker, mock_session):
    respond(mocker, mock_session)

    result = make(mocker, allow_trigger=True, trigger_jobs=ALLOWED).trigger_build(fullname='Branch-Retail/cloud/web-a')

    assert result == {'job': 'Branch-Retail/cloud/web-a', 'action': 'build', 'parameterised': False, 'dryRun': True}
    assert not posts(mock_session)


def test_confirm_starts_the_build_and_reports_the_queue_item(mocker, mock_session):
    respond(mocker, mock_session, location='https://example.com/queue/item/42/')

    jenkins = make(mocker, allow_trigger=True, trigger_jobs=' Branch-Retail/cloud/web-a/ ,x')
    result = jenkins.trigger_build(fullname='/Branch-Retail/cloud/web-a/', confirm=True)

    assert result['dryRun'] is False
    assert result['queueItem'] == 42
    assert result['queueUrl'] == 'https://example.com/queue/item/42/'
    [post] = posts(mock_session)
    assert post['url'] == 'https://example.com/job/Branch-Retail/job/cloud/job/web-a/build'


def test_parameterised_job_uses_build_with_parameters_and_defaults(mocker, mock_session):
    respond(mocker, mock_session, parameterised=True, location='https://example.com/queue/item/7/')

    result = make(mocker, allow_trigger=True, trigger_jobs=ALLOWED).trigger_build(
        fullname='Branch-Retail/cloud/01-common', confirm=True
    )

    assert result['action'] == 'buildWithParameters'
    [post] = posts(mock_session)
    assert post['url'].endswith('/job/01-common/buildWithParameters')
    assert post['data'] is None


def test_not_buildable_job_is_refused(mocker, mock_session):
    respond(mocker, mock_session, buildable=False)

    with pytest.raises(ValueError, match='not a buildable job'):
        make(mocker, allow_trigger=True, trigger_jobs=ALLOWED).trigger_build(
            fullname='Branch-Retail/cloud/web-a', confirm=True
        )

    assert not posts(mock_session)


def test_allowed_folders_still_apply(mocker, mock_session):
    jenkins = make(mocker, allow_trigger=True, trigger_jobs='Other/job', allowed_folders='Branch-Retail')

    with pytest.raises(PermissionError, match='outside the allowed folders'):
        jenkins.trigger_build(fullname='Other/job', confirm=True)


def _tool_names(env):
    code = (
        'import asyncio; from mcp_jenkins.server import mcp; '
        'print(",".join(sorted(t.name for t in asyncio.run(mcp.list_tools()))))'
    )
    out = subprocess.run(  # noqa: S603
        [sys.executable, '-W', 'ignore', '-c', code],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.strip().splitlines()[-1].split(','))


def test_tool_is_not_registered_unless_enabled():
    assert 'trigger_build' not in _tool_names({'jenkins_allow_trigger': 'false'})


def test_tool_is_registered_when_enabled():
    names = _tool_names({'jenkins_allow_trigger': 'true'})

    assert 'trigger_build' in names
    assert 'list_builds' in names
