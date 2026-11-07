import json
import re

import pytest
from pytest_mock import MockerFixture
from requests.exceptions import HTTPError

from mcp_jenkins.jenkins import Jenkins
from mcp_jenkins.jenkins.chain import chain_status
from mcp_jenkins.server import chain as chain_tool

ENTRY = 'Retail/01-common'
CHAIN = ['Retail/01-common', 'Retail/02-server', 'Retail/90-war-storage']
T0 = 1_000_000_000_000  # entry build start, ms
NOW_S = (T0 + 40 * 60_000) / 1000  # "now" is 40 minutes later


def path_of(name):
    return '/'.join(f'job/{part}' for part in name.split('/'))


def cause(project, number):
    return [{'causes': [{'upstreamProject': project, 'upstreamBuild': number}]}]


def build(number, result='SUCCESS', *, at=0, minutes=2, building=False, actions=None):
    return {
        'number': number,
        'result': None if building else result,
        'building': building,
        'timestamp': T0 + at * 60_000,
        'duration': 0 if building else minutes * 60_000,
        'actions': actions if actions is not None else [{}],
    }


class FakeJenkins:
    """Answers GETs for job pages from a dict of job fullname -> {builds, inQueue}."""

    def __init__(self, mocker: MockerFixture, jobs: dict) -> None:
        self.jobs = {path_of(name): data for name, data in jobs.items()}
        self.session = mocker.Mock()
        self.session.request.side_effect = self.respond
        mocker.patch('mcp_jenkins.jenkins.rest_client.requests.Session', autospec=True, return_value=self.session)
        mocker.patch.object(Jenkins, 'crumb_header', new_callable=mocker.PropertyMock, return_value={})
        mocker.patch('mcp_jenkins.jenkins.chain.time.time', return_value=NOW_S)
        self.client = Jenkins(url='https://example.com/', username='u', password='p')

    def respond(self, *, method: str, url: str, **_kwargs: object) -> '_Response':  # noqa: ARG002
        route = url.removeprefix('https://example.com/')
        job_path, _, _query = route.partition('/api/json')
        direct = re.match(r'^(.*)/(\d+)$', job_path)
        response = _Response()
        if direct and direct.group(1) in self.jobs:
            found = [b for b in self.jobs[direct.group(1)]['builds'] if b['number'] == int(direct.group(2))]
            if found:
                response.payload = found[0]
                return response
        elif job_path in self.jobs:
            data = self.jobs[job_path]
            response.payload = {'buildable': True, 'inQueue': data.get('inQueue', False), 'builds': data['builds']}
            return response
        response.status = 404
        return response

    def methods(self):
        return {call.kwargs['method'] for call in self.session.request.call_args_list}


class _Response:
    status = 200
    payload = None

    @property
    def status_code(self):
        return self.status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status >= 400:
            raise HTTPError(response=self)


def healthy():
    return {
        'Retail/01-common': {'builds': [build(5, at=0, minutes=3), build(4, at=-200)]},
        'Retail/02-server': {'builds': [build(8, at=4, minutes=5, actions=cause('Retail/01-common', 5))]},
        'Retail/90-war-storage': {'builds': [build(12, at=10, minutes=30, actions=cause('Retail/02-server', 8))]},
    }


def run(fake: FakeJenkins, **kwargs: int | None) -> dict:
    return chain_status(fake.client, entry=ENTRY, chain=CHAIN, **kwargs)


class TestVerdicts:
    def test_passed_through_the_final_job(self, mocker):
        fake = FakeJenkins(mocker, healthy())

        status = run(fake)

        assert status['verdict'] == 'passed'
        assert status['stoppedAt'] is None
        assert status['runningAt'] is None
        assert status['finalJob'] == 'Retail/90-war-storage'
        assert status['attribution'] == ['upstream']
        assert [(r['job'], r['number'], r['state']) for r in status['rows']] == [
            ('Retail/01-common', 5, 'success'),
            ('Retail/02-server', 8, 'success'),
            ('Retail/90-war-storage', 12, 'success'),
        ]
        assert status['summary'] == 'passed through 90-war-storage #12 in 40 min'

    def test_failed_midway_names_the_job_and_leaves_the_rest_not_started(self, mocker):
        jobs = healthy()
        jobs['Retail/02-server']['builds'] = [build(8, 'FAILURE', at=4, actions=cause('Retail/01-common', 5))]
        jobs['Retail/90-war-storage'] = {'builds': [build(11, at=-500, actions=cause('Retail/02-server', 7))]}
        status = run(FakeJenkins(mocker, jobs))

        assert status['verdict'] == 'failed'
        assert status['stoppedAt'] == 'Retail/02-server'
        assert [r['state'] for r in status['rows']] == ['success', 'failed', 'notstarted']
        assert status['summary'] == 'stopped at 02-server #8 FAILURE'

    def test_aborted_is_its_own_verdict(self, mocker):
        jobs = healthy()
        jobs['Retail/02-server']['builds'] = [build(8, 'ABORTED', at=4, actions=cause('Retail/01-common', 5))]
        jobs['Retail/90-war-storage'] = {'builds': []}

        status = run(FakeJenkins(mocker, jobs))

        assert status['verdict'] == 'aborted'
        assert status['stoppedAt'] == 'Retail/02-server'
        assert status['summary'] == 'stopped at 02-server #8 ABORTED'

    def test_unstable_stops_the_chain(self, mocker):
        jobs = healthy()
        jobs['Retail/02-server']['builds'] = [build(8, 'UNSTABLE', at=4, actions=cause('Retail/01-common', 5))]
        jobs['Retail/90-war-storage'] = {'builds': []}

        status = run(FakeJenkins(mocker, jobs))

        assert status['verdict'] == 'failed'
        assert status['summary'] == 'stopped at 02-server #8 UNSTABLE'

    def test_still_running_reports_the_running_job_and_elapsed_time(self, mocker):
        jobs = healthy()
        jobs['Retail/02-server']['builds'] = [
            build(8, at=4, building=True, actions=cause('Retail/01-common', 5)),
        ]
        jobs['Retail/90-war-storage'] = {'builds': []}

        status = run(FakeJenkins(mocker, jobs))

        assert status['verdict'] == 'running'
        assert status['runningAt'] == 'Retail/02-server'
        running = status['rows'][1]
        assert running['state'] == 'running'
        assert running['durationMs'] == 36 * 60_000  # now - start, not Jenkins' 0
        assert status['summary'] == 'running at 02-server #8 (1 of 3 done, 40 min)'

    def test_waiting_between_jobs(self, mocker):
        jobs = healthy()
        jobs['Retail/02-server'] = {'builds': []}
        jobs['Retail/90-war-storage'] = {'builds': []}

        status = run(FakeJenkins(mocker, jobs))

        assert status['verdict'] == 'waiting'
        assert [r['state'] for r in status['rows']] == ['success', 'notstarted', 'notstarted']
        assert status['summary'] == 'waiting for 02-server to start after 01-common #5'

    def test_a_queued_next_job_is_shown_as_queued(self, mocker):
        jobs = healthy()
        jobs['Retail/02-server'] = {'builds': [], 'inQueue': True}
        jobs['Retail/90-war-storage'] = {'builds': []}

        status = run(FakeJenkins(mocker, jobs))

        assert status['verdict'] == 'waiting'
        assert status['rows'][1]['state'] == 'queued'
        assert status['summary'] == 'waiting for 02-server to run after 01-common #5'

    def test_the_entry_job_alone_when_no_chain_is_given(self, mocker):
        fake = FakeJenkins(mocker, healthy())

        status = chain_status(fake.client, entry=ENTRY)

        assert status['verdict'] == 'passed'
        assert status['finalJob'] == ENTRY
        assert len(status['rows']) == 1


class TestAttribution:
    def test_builds_without_cause_information_fall_back_to_start_time(self, mocker):
        jobs = healthy()
        jobs['Retail/02-server'] = {'builds': [build(8, at=4), build(7, at=-300)]}  # #7 began before the entry
        jobs['Retail/90-war-storage'] = {'builds': [build(12, at=10, minutes=30)]}

        status = run(FakeJenkins(mocker, jobs))

        assert status['verdict'] == 'passed'
        assert status['attribution'] == ['time']
        assert [r['number'] for r in status['rows']] == [5, 8, 12]

    def test_both_methods_are_reported_when_mixed(self, mocker):
        jobs = healthy()
        jobs['Retail/90-war-storage'] = {'builds': [build(12, at=10, minutes=30)]}

        assert run(FakeJenkins(mocker, jobs))['attribution'] == ['time', 'upstream']

    def test_a_build_caused_by_a_different_upstream_build_is_not_ours(self, mocker):
        jobs = healthy()
        jobs['Retail/02-server']['builds'] = [build(8, at=4, actions=cause('Retail/01-common', 4))]
        jobs['Retail/90-war-storage'] = {'builds': []}

        status = run(FakeJenkins(mocker, jobs))

        assert status['rows'][1]['state'] == 'notstarted'
        assert status['verdict'] == 'waiting'

    def test_a_build_started_by_a_person_is_not_attributed_by_time(self, mocker):
        jobs = healthy()
        by_user = [{'causes': [{'userId': 'someone', 'shortDescription': 'Started by user someone'}]}]
        jobs['Retail/02-server']['builds'] = [build(8, at=4, actions=by_user)]
        jobs['Retail/90-war-storage'] = {'builds': []}

        status = run(FakeJenkins(mocker, jobs))

        assert status['rows'][1]['state'] == 'notstarted'

    def test_an_older_entry_build_can_be_followed(self, mocker):
        jobs = healthy()
        jobs['Retail/01-common']['builds'] = [build(6, at=60), build(5, at=0, minutes=3)]
        fake = FakeJenkins(mocker, jobs)

        status = run(fake, entry_number=5)

        assert status['rows'][0]['number'] == 5
        assert status['verdict'] == 'passed'

    def test_an_entry_build_outside_the_window_is_fetched_directly(self, mocker):
        fake = FakeJenkins(mocker, healthy())
        fake.jobs[path_of(ENTRY)]['builds'] = [build(n, at=1000 + n) for n in range(100, 140)] + [build(5, at=0)]
        fake.jobs[path_of(ENTRY)]['builds'][-1]['number'] = 5

        status = chain_status(fake.client, entry=ENTRY, chain=CHAIN, entry_number=5)

        assert status['rows'][0]['number'] == 5

    def test_an_unknown_entry_build_is_an_error(self, mocker):
        with pytest.raises(ValueError, match='No build #99'):
            run(FakeJenkins(mocker, healthy()), entry_number=99)


class TestInputs:
    @pytest.mark.parametrize(
        'name',
        ['', '   ', '../x', 'a/../b', 'a?b', 'a#b', 'a%2fb', 'a\\b', 'https://evil.example/x', 'a\nb', 'x' * 201],
    )
    def test_bad_names_are_refused_before_any_request(self, mocker, name):
        fake = FakeJenkins(mocker, healthy())

        with pytest.raises(ValueError, match='Invalid'):
            chain_status(fake.client, entry=name)
        with pytest.raises(ValueError, match='Invalid'):
            chain_status(fake.client, entry=ENTRY, chain=[name])

        fake.session.request.assert_not_called()

    def test_too_long_a_chain_is_refused(self, mocker):
        fake = FakeJenkins(mocker, healthy())

        with pytest.raises(ValueError, match='at most 30'):
            chain_status(fake.client, entry=ENTRY, chain=[f'Retail/{n}' for n in range(31)])

    @pytest.mark.parametrize('number', [0, -1, True])
    def test_a_bad_entry_number_is_refused(self, mocker, number):
        with pytest.raises(ValueError, match='positive'):
            chain_status(FakeJenkins(mocker, healthy()).client, entry=ENTRY, entry_number=number)

    def test_a_missing_job_is_a_clear_error(self, mocker):
        with pytest.raises(ValueError, match='Job not found: Retail/nope'):
            chain_status(FakeJenkins(mocker, healthy()).client, entry='Retail/nope')

    def test_a_folder_is_not_a_job(self, mocker):
        fake = FakeJenkins(mocker, healthy())
        fake.session.request.side_effect = lambda **_: _folder()

        with pytest.raises(ValueError, match='cannot have builds'):
            chain_status(fake.client, entry='Retail')

    def test_only_get_requests_are_made(self, mocker):
        fake = FakeJenkins(mocker, healthy())

        run(fake)

        assert fake.methods() == {'GET'}

    def test_the_folder_allowlist_still_applies(self, mocker):
        fake = FakeJenkins(mocker, healthy())
        fake.client._allowed_folders = ['Other']

        with pytest.raises(PermissionError):
            run(fake)

    def test_the_answer_is_compact(self, mocker):
        status = run(FakeJenkins(mocker, healthy()))

        assert len(json.dumps(status)) < 1100


def _folder():
    response = _Response()
    response.payload = {'jobs': []}
    return response


class TestWaiting:
    @pytest.fixture
    def clock(self, mocker):
        state = {'now': 0.0, 'sleeps': []}

        async def sleep(seconds):
            state['sleeps'].append(seconds)
            state['now'] += seconds

        mocker.patch('mcp_jenkins.server.chain.asyncio.sleep', sleep)
        mocker.patch('mcp_jenkins.server.chain.time.monotonic', lambda: state['now'])
        mocker.patch('mcp_jenkins.server.chain.jenkins', return_value=object())
        return state

    @staticmethod
    def feed(mocker: MockerFixture, verdicts: list[str]) -> object:
        answers = [{'verdict': v, 'rows': [{'number': 5}]} for v in verdicts]
        return mocker.patch('mcp_jenkins.server.chain.chain_status', side_effect=answers)

    @pytest.mark.asyncio
    async def test_no_wait_answers_once(self, mocker, clock):
        fake = self.feed(mocker, ['running'])

        result = await chain_tool.get_chain_status(mocker.Mock(), entry=ENTRY, chain=CHAIN)

        assert result['verdict'] == 'running'
        assert fake.call_count == 1
        assert clock['sleeps'] == []

    @pytest.mark.asyncio
    async def test_waits_until_the_chain_finishes(self, mocker, clock):
        fake = self.feed(mocker, ['running', 'running', 'passed'])

        result = await chain_tool.get_chain_status(mocker.Mock(), entry=ENTRY, chain=CHAIN, wait_seconds=30)

        assert result['verdict'] == 'passed'
        assert clock['sleeps'] == [5, 5]
        assert fake.call_count == 3

    @pytest.mark.asyncio
    async def test_gives_up_when_the_time_is_up(self, mocker, clock):
        fake = self.feed(mocker, ['running'] * 20)

        result = await chain_tool.get_chain_status(mocker.Mock(), entry=ENTRY, chain=CHAIN, wait_seconds=12)

        assert result['verdict'] == 'running'
        assert sum(clock['sleeps']) <= 12
        assert fake.call_count == len(clock['sleeps']) + 1

    @pytest.mark.asyncio
    async def test_wait_is_clamped_to_fifty_seconds(self, mocker, clock):
        self.feed(mocker, ['running'] * 40)

        await chain_tool.get_chain_status(mocker.Mock(), entry=ENTRY, chain=CHAIN, wait_seconds=10_000)

        assert sum(clock['sleeps']) <= 50

    @pytest.mark.asyncio
    async def test_a_negative_wait_answers_once(self, mocker, clock):
        fake = self.feed(mocker, ['waiting'])

        await chain_tool.get_chain_status(mocker.Mock(), entry=ENTRY, chain=CHAIN, wait_seconds=-5)

        assert fake.call_count == 1

    @pytest.mark.asyncio
    async def test_a_finished_chain_returns_at_once(self, mocker, clock):
        for verdict in ('passed', 'failed', 'aborted'):
            self.feed(mocker, [verdict])

            result = await chain_tool.get_chain_status(mocker.Mock(), entry=ENTRY, chain=CHAIN, wait_seconds=50)

            assert result['verdict'] == verdict
        assert clock['sleeps'] == []

    @pytest.mark.asyncio
    async def test_later_polls_follow_the_same_entry_build(self, mocker, clock):
        fake = self.feed(mocker, ['running', 'passed'])

        await chain_tool.get_chain_status(mocker.Mock(), entry=ENTRY, chain=CHAIN, wait_seconds=30)

        assert [c.kwargs['entry_number'] for c in fake.call_args_list] == [None, 5]
