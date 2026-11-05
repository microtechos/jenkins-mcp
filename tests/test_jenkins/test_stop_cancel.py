import os
import subprocess
import sys

import pytest
from requests.exceptions import HTTPError

from mcp_jenkins.jenkins import Jenkins

JOB = 'Branch-Retail/cloud/web-a'
ALLOWED = f'Branch-Retail/cloud/01-common,{JOB}'
BASE = 'https://example.com'


@pytest.fixture(autouse=True)
def mock_session(mocker):
    session = mocker.Mock()
    mocker.patch('mcp_jenkins.jenkins.rest_client.requests.Session', autospec=True, return_value=session)
    return session


def make(mocker, **kwargs: object):
    mocker.patch.object(Jenkins, 'crumb_header', new_callable=mocker.PropertyMock, return_value={})
    kwargs.setdefault('allow_trigger', True)
    kwargs.setdefault('trigger_jobs', ALLOWED)
    return Jenkins(url=BASE + '/', username='u', password='p', **kwargs)


def respond(mocker, session, payload=None, *, status=None):
    def handler(**kw: object):
        if kw['method'] == 'GET':
            if status:
                resp = mocker.Mock(status_code=status)
                raise HTTPError(response=resp)
            return mocker.Mock(json=lambda: payload)
        return mocker.Mock(headers={})

    session.request.side_effect = handler


def posts(session):
    return [c.kwargs for c in session.request.call_args_list if c.kwargs['method'] == 'POST']


class TestStopBuild:
    def test_disabled_by_default(self, mocker, mock_session):
        with pytest.raises(PermissionError, match='disabled'):
            make(mocker, allow_trigger=False).stop_build(fullname=JOB, number=3, confirm=True)

        assert mock_session.request.call_count == 0

    @pytest.mark.parametrize('fullname', ['Branch-Retail/cloud', 'Branch-Retail/cloud/web-b', 'other/job', ''])
    def test_job_outside_the_list_is_refused(self, mocker, mock_session, fullname):
        with pytest.raises(PermissionError, match='not in the stop allowlist'):
            make(mocker).stop_build(fullname=fullname, number=3, confirm=True)

        assert mock_session.request.call_count == 0

    @pytest.mark.parametrize('number', [0, -1])
    def test_invalid_build_number(self, mocker, number):
        with pytest.raises(ValueError, match='Invalid build number'):
            make(mocker).stop_build(fullname=JOB, number=number)

    def test_finished_build_is_refused(self, mocker, mock_session):
        respond(mocker, mock_session, {'number': 3, 'building': False, 'result': 'SUCCESS'})

        with pytest.raises(ValueError, match='is not running'):
            make(mocker).stop_build(fullname=JOB, number=3, confirm=True)

        assert not posts(mock_session)

    def test_dry_run_is_the_default_and_sends_no_post(self, mocker, mock_session):
        respond(mocker, mock_session, {'number': 3, 'building': True})

        result = make(mocker).stop_build(fullname=JOB, number=3)

        assert result == {'job': JOB, 'number': 3, 'action': 'stop', 'building': True, 'dryRun': True}
        assert not posts(mock_session)

    def test_confirm_stops_the_build(self, mocker, mock_session):
        respond(mocker, mock_session, {'number': 3, 'building': True})

        result = make(mocker).stop_build(fullname=f'/{JOB}/', number=3, confirm=True)

        assert result['dryRun'] is False
        [post] = posts(mock_session)
        assert post['url'] == f'{BASE}/job/Branch-Retail/job/cloud/job/web-a/3/stop'


class TestCancelQueueItem:
    def task(self, name='web-a', path='Branch-Retail/job/cloud/job'):
        return {'id': 42, 'task': {'name': name, 'url': f'{BASE}/job/{path}/{name}/'}}

    def test_disabled_by_default(self, mocker, mock_session):
        with pytest.raises(PermissionError, match='disabled'):
            make(mocker, allow_trigger=False).cancel_queue_item(id=42, confirm=True)

        assert mock_session.request.call_count == 0

    @pytest.mark.parametrize('id_', [0, -5])
    def test_invalid_id(self, mocker, id_):
        with pytest.raises(ValueError, match='Invalid queue item id'):
            make(mocker).cancel_queue_item(id=id_)

    def test_item_of_an_allowlisted_job_dry_run(self, mocker, mock_session):
        respond(mocker, mock_session, self.task())

        result = make(mocker).cancel_queue_item(id=42)

        assert result == {'queueItem': 42, 'job': JOB, 'action': 'cancel', 'dryRun': True}
        assert not posts(mock_session)

    def test_confirm_cancels_the_item(self, mocker, mock_session):
        respond(mocker, mock_session, self.task())

        result = make(mocker).cancel_queue_item(id=42, confirm=True)

        assert result['dryRun'] is False
        [post] = posts(mock_session)
        assert post['url'] == f'{BASE}/queue/cancelItem?id=42'

    def test_item_of_another_job_is_refused_and_nothing_is_sent(self, mocker, mock_session):
        respond(mocker, mock_session, self.task(name='06-server', path='Branch-Retail/job/cloud/job'))

        with pytest.raises(PermissionError, match='not in the stop allowlist'):
            make(mocker).cancel_queue_item(id=42, confirm=True)

        assert not posts(mock_session)

    @pytest.mark.parametrize(
        'url',
        [
            '',
            'https://elsewhere.example/job/Branch-Retail/job/cloud/job/web-a/',
            f'{BASE}/computer/x/',
            f'{BASE}/job/a/b/',
        ],
    )
    def test_item_with_a_task_that_is_not_one_of_our_jobs_is_refused(self, mocker, mock_session, url):
        respond(mocker, mock_session, {'id': 42, 'task': {'url': url}})

        with pytest.raises(PermissionError, match='not in the stop allowlist'):
            make(mocker).cancel_queue_item(id=42, confirm=True)

        assert not posts(mock_session)

    def test_percent_encoded_names_are_decoded(self, mocker, mock_session):
        respond(mocker, mock_session, {'id': 42, 'task': {'url': f'{BASE}/job/My%20Folder/job/my%20job/'}})

        with pytest.raises(PermissionError, match='My Folder/my job'):
            make(mocker).cancel_queue_item(id=42)

    def test_unknown_item(self, mocker, mock_session):
        respond(mocker, mock_session, status=404)

        with pytest.raises(ValueError, match='not found'):
            make(mocker).cancel_queue_item(id=42, confirm=True)


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


def test_the_write_tools_exist_only_when_enabled():
    off = _tool_names({'jenkins_allow_trigger': 'false'})
    on = _tool_names({'jenkins_allow_trigger': 'true'})

    assert not off & {'trigger_build', 'stop_build', 'cancel_queue_item'}
    assert {'trigger_build', 'stop_build', 'cancel_queue_item'} <= on
    assert not on & {'build_item', 'set_item_config', 'set_node_config', 'run_groovy_script'}


CHAIN = 'Branch-Retail/cloud/06-server'


class TestStopJobs:
    def test_stop_build_accepts_a_chain_job_from_the_stop_list(self, mocker, mock_session):
        respond(mocker, mock_session, {'number': 4, 'building': True})

        result = make(mocker, stop_jobs=CHAIN).stop_build(fullname=CHAIN, number=4, confirm=True)

        assert result['job'] == CHAIN
        [post] = posts(mock_session)
        assert post['url'].endswith('/job/06-server/4/stop')

    def test_trigger_build_never_accepts_a_stop_only_job(self, mocker, mock_session):
        with pytest.raises(PermissionError, match='not in the trigger allowlist'):
            make(mocker, stop_jobs=CHAIN).trigger_build(fullname=CHAIN, confirm=True)

        assert mock_session.request.call_count == 0

    def test_cancel_queue_item_accepts_a_chain_job_from_the_stop_list(self, mocker, mock_session):
        respond(mocker, mock_session, {'id': 9, 'task': {'url': f'{BASE}/job/Branch-Retail/job/cloud/job/06-server/'}})

        result = make(mocker, stop_jobs=CHAIN).cancel_queue_item(id=9, confirm=True)

        assert result['job'] == CHAIN
        assert len(posts(mock_session)) == 1

    def test_trigger_jobs_can_also_be_stopped(self, mocker, mock_session):
        respond(mocker, mock_session, {'number': 4, 'building': True})

        assert make(mocker, stop_jobs=CHAIN).stop_build(fullname=JOB, number=4)['job'] == JOB

    def test_a_job_in_neither_list_is_refused(self, mocker, mock_session):
        with pytest.raises(PermissionError, match='not in the stop allowlist'):
            make(mocker, stop_jobs=CHAIN).stop_build(fullname='Other/job', number=4, confirm=True)

        assert mock_session.request.call_count == 0
