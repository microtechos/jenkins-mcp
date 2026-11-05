import json

import pytest

from mcp_jenkins.jenkins import Jenkins

JOB = 'Branch-Retail/cloud/web-a'
ALLOWED = f'Branch-Retail/cloud/01-common,{JOB}'

CONFIG_WITH_CONTEXT = """<project>
  <scm><userRemoteConfigs><hudson.plugins.git.UserRemoteConfig><url>git@github.com:o/r.git</url>
  </hudson.plugins.git.UserRemoteConfig></userRemoteConfigs>
  <branches><hudson.plugins.git.BranchSpec><name>*/release/production</name></hudson.plugins.git.BranchSpec></branches></scm>
  <properties><hudson.model.ParametersDefinitionProperty><parameterDefinitions>
    <hudson.model.StringParameterDefinition><name>BRANCH</name><defaultValue>main</defaultValue></hudson.model.StringParameterDefinition>
    <hudson.model.StringParameterDefinition><name>DEPLOY_TOKEN</name><defaultValue>zzz</defaultValue></hudson.model.StringParameterDefinition>
  </parameterDefinitions></hudson.model.ParametersDefinitionProperty></properties>
  <publishers><hudson.tasks.BuildTrigger><childProjects>02-report</childProjects></hudson.tasks.BuildTrigger></publishers>
</project>"""


@pytest.fixture(autouse=True)
def mock_session(mocker):
    session = mocker.Mock()
    mocker.patch('mcp_jenkins.jenkins.rest_client.requests.Session', autospec=True, return_value=session)
    return session


def make(mocker, **kwargs: object):
    mocker.patch.object(Jenkins, 'crumb_header', new_callable=mocker.PropertyMock, return_value={})
    kwargs.setdefault('allow_trigger', True)
    kwargs.setdefault('trigger_jobs', ALLOWED)
    return Jenkins(url='https://example.com/', username='u', password='p', **kwargs)


def respond(mocker, session, *, config='<project/>', location='', build=None):
    info = {'buildable': True, 'property': []}

    def handler(**kw: object):
        if kw['method'] == 'GET':
            url = str(kw['url'])
            if url.endswith('/config.xml'):
                return mocker.Mock(text=config)
            if '/api/json?tree=number,building' in url:
                return mocker.Mock(json=lambda: build or {'number': 3, 'building': True})
            return mocker.Mock(json=lambda: info)
        return mocker.Mock(headers={'Location': location} if location else {})

    session.request.side_effect = handler


def posts(session):
    return [c.kwargs for c in session.request.call_args_list if c.kwargs['method'] == 'POST']


class TestDryRunContext:
    def test_lists_branch_default_parameters_and_downstream(self, mocker, mock_session):
        respond(mocker, mock_session, config=CONFIG_WITH_CONTEXT)

        result = make(mocker).trigger_build(fullname=JOB)

        assert result['branches'] == ['*/release/production']
        assert result['downstream'] == ['02-report']
        assert {'name': 'BRANCH', 'type': 'StringParameterDefinition', 'default': 'main'} in result['parameters']
        assert 'zzz' not in str(result)

    def test_unreadable_config_does_not_block_the_dry_run(self, mocker, mock_session):
        respond(mocker, mock_session, config='not xml at all <')

        result = make(mocker).trigger_build(fullname=JOB)

        assert result['dryRun'] is True
        assert 'branches' not in result


class TestAuditAndCap:
    def test_every_confirmed_write_is_logged_without_secrets(self, mocker, mock_session, tmp_path):
        log = tmp_path / 'sub' / 'audit.jsonl'
        respond(mocker, mock_session, location='https://example.com/queue/item/42/')
        jenkins = make(mocker, audit_log=str(log))

        jenkins.trigger_build(fullname=JOB)  # dry run: not logged
        jenkins.trigger_build(fullname=JOB, confirm=True)

        [line] = log.read_text(encoding='utf-8').splitlines()
        record = json.loads(line)
        assert (record['action'], record['job'], record['queueItem'], record['user']) == ('trigger_build', JOB, 42, 'u')
        assert 'ts' in record
        assert 'p' not in record.values()

    def test_an_unwritable_audit_path_never_breaks_the_action(self, mocker, mock_session, tmp_path):
        respond(mocker, mock_session, location='https://example.com/queue/item/1/')
        jenkins = make(mocker, audit_log=str(tmp_path))  # a directory, not a file

        assert jenkins.trigger_build(fullname=JOB, confirm=True)['queueItem'] == 1

    def test_confirmed_starts_are_capped_per_session(self, mocker, mock_session):
        respond(mocker, mock_session, location='https://example.com/queue/item/1/')
        jenkins = make(mocker, max_starts=2)

        jenkins.trigger_build(fullname=JOB, confirm=True)
        jenkins.trigger_build(fullname=JOB, confirm=True)
        with pytest.raises(PermissionError, match='Start limit reached'):
            jenkins.trigger_build(fullname=JOB, confirm=True)

        assert len(posts(mock_session)) == 2

    def test_dry_runs_do_not_count_against_the_cap(self, mocker, mock_session):
        respond(mocker, mock_session)
        jenkins = make(mocker, max_starts=1)

        for _ in range(5):
            jenkins.trigger_build(fullname=JOB)

        assert not posts(mock_session)

    def test_stop_is_logged_too(self, mocker, mock_session, tmp_path):
        log = tmp_path / 'audit.jsonl'
        respond(mocker, mock_session)

        make(mocker, audit_log=str(log)).stop_build(fullname=JOB, number=3, confirm=True)

        assert '"stop_build"' in log.read_text(encoding='utf-8')


class TestCrumbRetryOnWrites:
    @staticmethod
    def crumb(mocker, value: str):  # noqa: ANN205
        return mocker.Mock(status_code=200, json=lambda: {'crumbRequestField': 'Jenkins-Crumb', 'crumb': value})

    def test_a_403_on_a_post_refreshes_the_crumb_and_retries_once(self, mocker, mock_session):
        ok = mocker.Mock(status_code=200)
        stale = mocker.Mock(status_code=403)
        mock_session.request.side_effect = [self.crumb(mocker, 'c1'), stale, self.crumb(mocker, 'c2'), ok]
        jenkins = Jenkins(url='https://example.com/', username='u', password='p')

        assert jenkins.request('POST', 'job/x/build') is ok
        crumb_fetches = [c for c in mock_session.request.call_args_list if 'crumbIssuer' in c.kwargs['url']]
        assert len(crumb_fetches) == 2
        assert len(posts(mock_session)) == 2
        assert posts(mock_session)[-1]['headers']['Jenkins-Crumb'] == 'c2'

    def test_a_second_403_is_not_retried_again(self, mocker, mock_session):
        denied = mocker.Mock(status_code=403)
        denied.raise_for_status.side_effect = RuntimeError('403')
        mock_session.request.side_effect = [self.crumb(mocker, 'c'), denied, self.crumb(mocker, 'c'), denied]
        jenkins = Jenkins(url='https://example.com/', username='u', password='p')

        with pytest.raises(RuntimeError, match='403'):
            jenkins.request('POST', 'job/x/build')

        assert mock_session.request.call_count == 4


class TestReadHardening:
    def test_query_patterns_are_length_capped(self, mocker):
        for kwargs in ({'class_pattern': 'a' * 201}, {'fullname_pattern': 'a' * 201}, {'color_pattern': 'a' * 201}):
            with pytest.raises(ValueError, match='pattern is longer'):
                make(mocker).query_items(**kwargs)

    def test_console_output_is_redacted(self, mocker, mock_session):
        lines = ['Started by user x', 'export DEPLOY_TOKEN=abc123', 'curl -u admin:s3cret http://h', 'done']
        mock_session.get.return_value = mocker.Mock(iter_lines=lambda decode_unicode: iter(lines))

        out = make(mocker).get_build_console_output(fullname='j', number=1)

        assert 'abc123' not in out
        assert 's3cret' not in out
        assert 'Started by user x' in out

    def test_a_url_with_credentials_is_refused(self, mocker):
        from mcp_jenkins.core.lifespan import jenkins

        lifespan_context = mocker.Mock(
            jenkins_url='https://user:secret@jenkins.example.com',
            jenkins_username='u',
            jenkins_password='p',
            jenkins_session_singleton=False,
        )
        ctx = mocker.Mock(request_context=mocker.Mock(lifespan_context=lifespan_context), session=mocker.Mock(spec=[]))

        with pytest.raises(ValueError, match='must not contain credentials'):
            jenkins(ctx)
