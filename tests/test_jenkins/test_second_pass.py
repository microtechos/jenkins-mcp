import json
import time

import pytest
from requests.exceptions import HTTPError

from mcp_jenkins.jenkins import Jenkins
from mcp_jenkins.jenkins.model.item import serialize_item
from mcp_jenkins.jenkins.redact import redact_config_xml, redact_data, redact_params, redact_text
from mcp_jenkins.jenkins.safe_regex import compile_safe
from mcp_jenkins.server.approval import start_message

JOB = 'Branch-Retail/cloud/web-a'
BASE = 'https://example.com'


@pytest.fixture(autouse=True)
def mock_session(mocker):
    session = mocker.Mock()
    mocker.patch('mcp_jenkins.jenkins.rest_client.requests.Session', autospec=True, return_value=session)
    return session


def make(mocker, **kwargs: object):
    mocker.patch.object(Jenkins, 'crumb_header', new_callable=mocker.PropertyMock, return_value={})
    return Jenkins(url=BASE + '/', username='u', password='p', **kwargs)


class TestSafeRegex:
    @pytest.mark.parametrize(
        'pattern',
        [
            r'\[ERROR\]|BUILD FAILURE|Finished: (FAILURE|ABORTED)',
            r'^Branch-Retail/',
            r'Exception|npm ERR',
            r'.*foo.*bar',
            r'\d{1,3}\.\d{1,3}',
            r'(?i)started by user \w+',
            r'(a|b)+',  # Python turns a one-character alternation into a character class: linear, so allowed
        ],
    )
    def test_ordinary_patterns_compile(self, pattern):
        assert compile_safe(pattern).pattern == pattern

    @pytest.mark.parametrize('pattern', [r'(a|a)*$', r'(a+)+$', r'(\d+\.)+x', r'(foo|bar)+', r'(.*a){5}', r'((a)|b)*'])
    def test_nested_or_alternated_repeats_are_refused(self, pattern):
        with pytest.raises(ValueError, match='hang the server'):
            compile_safe(pattern)

    def test_an_invalid_pattern_is_a_clear_error(self):
        with pytest.raises(ValueError, match='not a valid regular expression'):
            compile_safe('(unclosed')

    def test_a_long_pattern_is_refused(self):
        with pytest.raises(ValueError, match='is longer than 200'):
            compile_safe('a' * 201)

    def test_the_tools_use_it(self, mocker, mock_session):
        jenkins = make(mocker)

        with pytest.raises(ValueError, match='hang the server'):
            jenkins.get_build_console_output(fullname='j', number=1, pattern='(a|a)*$')
        with pytest.raises(ValueError, match='hang the server'):
            jenkins.query_items(fullname_pattern='(a+)+$')
        with pytest.raises(ValueError, match='hang the server'):
            jenkins.get_jobs_status(fullname_pattern='(a+)+$')


class TestRedactionShapes:
    @pytest.mark.parametrize(
        ('text', 'secret'),
        [
            ('keytool -storepass storepw1 -keypass keypw2', 'storepw1'),
            ('keytool -srcstorepass srcpw3 -destkeypass destpw4', 'destpw4'),
            ('docker login -u me -p dockerpw5 registry.example', 'dockerpw5'),
            ('sshpass -p sshpw6 ssh host', 'sshpw6'),
            ('mysql -h db -u root -pmysqlpw7', 'mysqlpw7'),
            ('{"password": "jsonpw8"}', 'jsonpw8'),
            ('password => "rubypw9"', 'rubypw9'),
            ('storePassword "gradlepw10"', 'gradlepw10'),
            ("keyPassword 'gradlepw11'", 'gradlepw11'),
            ('DB_PASS=dbpw12', 'dbpw12'),
            ('pwd=pwdpw13 and pw=pwpw14', 'pwdpw13'),
            ('Authorization: Basic YWJjOmRlZmdoaWprbG1ub3A=', 'YWJjOmRlZmdoaWprbG1ub3A'),
            (
                'git clone https://ghp_abcdefghijklmnopqrstuvwxyz1234@github.com/o/r.git',
                'abcdefghijklmnopqrstuvwxyz1234',
            ),
            ('password = "a b c secret words"', 'secret words'),
        ],
    )
    def test_secret_is_masked(self, text, secret):
        out = redact_text(text)

        assert secret not in out
        assert 'REDACTED' in out

    @pytest.mark.parametrize(
        'text',
        [
            'we bypass the cache and the test passed',
            'compass pass-through tokenizer',
            'npm run build:prod',
            'Authorization: Basic configuration page',
            'export PASS_TOKEN=$FROM_ENV',
            'https://github.com/owner/repo.git',
        ],
    )
    def test_ordinary_text_is_unchanged(self, text):
        assert redact_text(text) == text

    def test_params_with_short_secret_names(self):
        out = redact_params({'DB_PASS': 'a', 'PWD': 'b', 'pw': 'c', 'BRANCH': 'main', 'bypass': 'ok'})

        assert out == {
            'DB_PASS': '[REDACTED]',
            'PWD': '[REDACTED]',
            'pw': '[REDACTED]',
            'BRANCH': 'main',
            'bypass': 'ok',
        }

    def test_nested_data_is_redacted(self):
        data = {
            'stdout': 'login with password=hunter2',
            'cases': [{'err': 'curl -u a:b http://h', 'password': 'x'}],
            'n': 3,
        }

        out = redact_data(data)

        assert 'hunter2' not in json.dumps(out)
        assert 'a:b' not in json.dumps(out)
        assert out['cases'][0]['password'] == '[REDACTED]'
        assert out['n'] == 3

    def test_redaction_work_is_bounded(self):
        for text, limit in (
            ('token-secret.' * 100_000, 8.0),
            ('<password ' * 20_000, 3.0),
            (('a' * 40 + 'pass' + 'b' * 40 + ' ') * 5_000, 3.0),
        ):
            start = time.time()
            redact_config_xml(text)
            assert time.time() - start < limit

    def test_huge_input_is_cut_and_marked(self):
        out = redact_text('x' * 2_500_000)

        assert out.endswith('[truncated: too large to redact]')
        assert len(out) < 2_100_000


class TestScopedViews:
    VIEW = {
        'name': 'All',
        'url': BASE + '/view/All/',
        'description': 'everything',
        'jobs': [
            {
                '_class': 'hudson.model.FreeStyleProject',
                'name': 'a',
                'url': BASE + '/job/Branch-Retail/job/a/',
                'color': 'blue',
            },
            {'_class': 'hudson.model.FreeStyleProject', 'name': 'b', 'url': BASE + '/job/Other/job/b/', 'color': 'red'},
        ],
        'views': [{'name': 'sub', 'url': BASE + '/view/All/view/sub/', 'extra': 'x'}],
        'property': [{'parameterDefinitions': [{'defaultParameterValue': {'value': 'secret'}}]}],
        'actions': [{'parameters': [{'name': 'DB_PASSWORD', 'value': 'secret'}]}],
    }

    def test_view_is_compact_and_has_no_parameters(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(json=lambda: self.VIEW)

        view = make(mocker).get_view(view_path='All', depth=3)

        assert 'secret' not in json.dumps(view)
        assert set(view) == {'name', 'url', 'description', 'jobs', 'views'}
        assert view['jobs'][0] == {
            'name': 'a',
            'url': BASE + '/job/Branch-Retail/job/a/',
            'color': 'blue',
            'kind': 'FreeStyleProject',
        }
        assert view['views'] == [{'name': 'sub', 'url': BASE + '/view/All/view/sub/'}]

    def test_depth_is_never_sent_to_jenkins(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(json=lambda: self.VIEW)

        make(mocker).get_view(view_path='All', depth=3)

        assert 'depth' not in mock_session.request.call_args.kwargs['url']

    def test_jobs_outside_the_allowed_folders_are_left_out(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(json=lambda: self.VIEW)

        view = make(mocker, allowed_folders='Branch-Retail').get_view(view_path='All')

        assert [job['name'] for job in view['jobs']] == ['a']

    def test_unknown_item_types_never_expose_properties_or_actions(self):
        item = serialize_item(
            {
                '_class': 'hudson.maven.MavenModuleSet',
                'name': 'm',
                'url': BASE + '/job/m/',
                'color': 'blue',
                'property': [{'parameterDefinitions': [{'defaultParameterValue': {'value': 'secret'}}]}],
                'actions': [{'parameters': [{'name': 'DB_PASSWORD', 'value': 'secret'}]}],
                'displayName': 'kept',
            }
        )

        dumped = item.model_dump(exclude_none=True)

        assert 'secret' not in json.dumps(dumped)
        assert 'property' not in dumped
        assert 'actions' not in dumped
        assert dumped['displayName'] == 'kept'


CONFIG = """<project>
  <scm><userRemoteConfigs><hudson.plugins.git.UserRemoteConfig><url>git@github.com:o/r.git</url>
  </hudson.plugins.git.UserRemoteConfig></userRemoteConfigs>
  <branches><hudson.plugins.git.BranchSpec><name>*/release/production</name></hudson.plugins.git.BranchSpec></branches></scm>
  <publishers><hudson.tasks.BuildTrigger><childProjects>02-report</childProjects></hudson.tasks.BuildTrigger></publishers>
</project>"""


def respond(mocker, session, *, configs, post_error=None, location='https://example.com/queue/item/9/'):
    """GET answers: the build info, then each config in `configs` in turn (the last one repeats)."""
    state = {'n': 0}
    info = {'buildable': True, 'property': []}

    def handler(**kw: object):
        if kw['method'] == 'GET':
            if str(kw['url']).endswith('/config.xml'):
                config = configs[min(state['n'], len(configs) - 1)]
                state['n'] += 1
                if isinstance(config, Exception):
                    raise config
                return mocker.Mock(text=config)
            return mocker.Mock(json=lambda: info)
        if post_error is not None:
            raise post_error
        return mocker.Mock(headers={'Location': location})

    session.request.side_effect = handler


def posts(session):
    return [c.kwargs for c in session.request.call_args_list if c.kwargs['method'] == 'POST']


class TestContextDigest:
    def test_dry_run_returns_a_digest_that_is_stable(self, mocker, mock_session):
        respond(mocker, mock_session, configs=[CONFIG])
        jenkins = make(mocker, allow_trigger=True, trigger_jobs=JOB)

        first = jenkins.trigger_build(fullname=JOB)
        second = jenkins.trigger_build(fullname=JOB)

        assert len(first['contextDigest']) == 64
        assert first['contextDigest'] == second['contextDigest']

    def test_a_confirmed_start_with_the_same_context_goes_through(self, mocker, mock_session):
        respond(mocker, mock_session, configs=[CONFIG])
        jenkins = make(mocker, allow_trigger=True, trigger_jobs=JOB)
        digest = jenkins.trigger_build(fullname=JOB)['contextDigest']

        result = jenkins.trigger_build(fullname=JOB, confirm=True, context_digest=digest)

        assert result['queueItem'] == 9
        assert len(posts(mock_session)) == 1

    def test_a_changed_job_is_refused_before_anything_is_sent(self, mocker, mock_session):
        changed = CONFIG.replace('release/production', 'features/experiment')
        respond(mocker, mock_session, configs=[CONFIG, changed])
        jenkins = make(mocker, allow_trigger=True, trigger_jobs=JOB)
        digest = jenkins.trigger_build(fullname=JOB)['contextDigest']

        with pytest.raises(PermissionError, match='changed since the dry run'):
            jenkins.trigger_build(fullname=JOB, confirm=True, context_digest=digest)

        assert not posts(mock_session)

    def test_an_unreadable_config_gives_a_null_digest_and_skips_the_check(self, mocker, mock_session):
        forbidden = HTTPError(response=mocker.Mock(status_code=403))
        respond(mocker, mock_session, configs=[forbidden])
        jenkins = make(mocker, allow_trigger=True, trigger_jobs=JOB)

        plan = jenkins.trigger_build(fullname=JOB)
        result = jenkins.trigger_build(fullname=JOB, confirm=True, context_digest=plan['contextDigest'])

        assert plan['contextDigest'] is None
        assert result['queueItem'] == 9

    def test_the_approval_message_shows_what_will_run(self):
        plan = {
            'job': JOB,
            'branches': ['*/release/production'],
            'parameters': [{'name': 'BRANCH', 'default': 'main'}],
            'downstream': ['02-report'],
            'contextDigest': 'x',
        }

        message = start_message(plan)

        assert JOB in message
        assert 'Branch: */release/production' in message
        assert 'BRANCH=main' in message
        assert 'Then starts: 02-report' in message

    def test_the_message_says_when_the_context_is_unknown(self):
        assert 'could not be read' in start_message({'job': JOB, 'contextDigest': None})

    def test_long_lists_are_shortened(self):
        message = start_message({'job': JOB, 'downstream': [f'job-{i}' for i in range(30)], 'contextDigest': 'x'})

        assert '(+18 more)' in message


BOOM = 'boom'


class TestFailedAttempts:
    def test_a_failed_post_still_counts_as_a_start_and_is_audited(self, mocker, mock_session, tmp_path):
        log = tmp_path / 'audit.jsonl'
        respond(mocker, mock_session, configs=[CONFIG], post_error=TimeoutError('read timed out'))
        jenkins = make(mocker, allow_trigger=True, trigger_jobs=JOB, max_starts=1, audit_log=str(log))

        with pytest.raises(TimeoutError):
            jenkins.trigger_build(fullname=JOB, confirm=True)
        with pytest.raises(PermissionError, match='Start limit reached'):
            jenkins.trigger_build(fullname=JOB, confirm=True)

        [record] = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        assert record['action'] == 'trigger_build_failed'
        assert record['error'] == 'TimeoutError'
        assert 'read timed out' not in json.dumps(record)

    def test_failed_stop_and_cancel_are_audited(self, mocker, mock_session, tmp_path):
        log = tmp_path / 'audit.jsonl'

        def handler(**kw: object):
            if kw['method'] == 'GET':
                if '/api/json?tree=number,building' in str(kw['url']):
                    return mocker.Mock(json=lambda: {'number': 3, 'building': True})
                return mocker.Mock(
                    json=lambda: {'id': 5, 'task': {'url': f'{BASE}/job/Branch-Retail/job/cloud/job/web-a/'}}
                )
            raise ConnectionError(BOOM)

        mock_session.request.side_effect = handler
        jenkins = make(mocker, allow_trigger=True, trigger_jobs=JOB, audit_log=str(log))

        with pytest.raises(ConnectionError):
            jenkins.stop_build(fullname=JOB, number=3, confirm=True)
        with pytest.raises(ConnectionError):
            jenkins.cancel_queue_item(id=5, confirm=True)

        actions = [json.loads(line)['action'] for line in log.read_text(encoding='utf-8').splitlines()]
        assert actions == ['stop_build_failed', 'cancel_queue_item_failed']
