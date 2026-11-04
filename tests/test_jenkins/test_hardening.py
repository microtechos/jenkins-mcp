import pytest

from mcp_jenkins.jenkins import Jenkins
from mcp_jenkins.jenkins.redact import redact_config_xml

BACKSLASH = chr(92)
NUL = chr(0)


@pytest.fixture(autouse=True)
def mock_session(mocker):
    session = mocker.Mock()
    mocker.patch('mcp_jenkins.jenkins.rest_client.requests.Session', autospec=True, return_value=session)
    return session


def make(mocker, **kwargs: object):
    mocker.patch.object(Jenkins, 'crumb_header', new_callable=mocker.PropertyMock, return_value={})
    return Jenkins(url='https://example.com/', username='u', password='p', **kwargs)


@pytest.mark.parametrize(
    'fullname',
    ['a/../b', '..', 'a//b', 'a/./b', 'a/b?x=1', 'a/b#frag', 'a/b%2e', 'a' + BACKSLASH + 'b', 'a/b' + NUL, 'a/ /b'],
)
def test_job_path_rejects_unsafe_names(mocker, fullname):
    with pytest.raises(ValueError, match='Invalid job fullname'):
        make(mocker)._job_path(fullname)


def test_job_path_quotes_segments(mocker):
    assert make(mocker)._job_path('Folder One/job two') == 'job/Folder%20One/job/job%20two'


@pytest.mark.parametrize('relative_path', ['../x', 'a/../b', 'a?b', 'a#b', 'a%2Fb', ''])
def test_artifact_path_rejects_traversal(mocker, relative_path):
    with pytest.raises(ValueError, match='Invalid artifact path'):
        make(mocker)._artifact_path(relative_path)


def test_artifact_path_quotes_segments(mocker):
    assert make(mocker)._artifact_path('dist/my app/index.html') == 'dist/my%20app/index.html'


@pytest.mark.parametrize('name', ['a/b', '..', 'a?b', 'a%2Fb'])
def test_node_name_rejects_unsafe_names(mocker, name):
    with pytest.raises(ValueError, match='Invalid'):
        make(mocker).get_node(name=name)


class TestAllowedFolders:
    def test_inside_is_allowed(self, mocker):
        jenkins = make(mocker, allowed_folders='Branch-Retail, Branch-Salon/')

        assert jenkins._job_path('Branch-Retail/x/job') == 'job/Branch-Retail/job/x/job/job'
        assert jenkins._job_path('Branch-Salon') == 'job/Branch-Salon'

    @pytest.mark.parametrize('fullname', ['Branch-Restaurant/x', 'Branch-RetailX/x', 'other'])
    def test_outside_is_refused(self, mocker, fullname):
        with pytest.raises(PermissionError, match='outside the allowed folders'):
            make(mocker, allowed_folders='Branch-Retail,Branch-Salon')._job_path(fullname)

    def test_empty_means_unrestricted(self, mocker):
        assert make(mocker, allowed_folders='')._job_path('anything/at/all') == 'job/anything/job/at/job/all'

    def test_listing_is_filtered_but_keeps_parent_folders(self, mocker, mock_session):
        folder = 'com.cloudbees.hudson.plugins.folder.Folder'
        job = 'hudson.model.FreeStyleProject'
        mock_session.request.return_value = mocker.Mock(
            json=lambda: {
                'jobs': [
                    {
                        '_class': folder,
                        'name': 'Branch-Retail',
                        'url': 'u',
                        'jobs': [{'_class': job, 'name': 'a', 'url': 'u', 'color': 'blue'}],
                    },
                    {
                        '_class': folder,
                        'name': 'Other',
                        'url': 'u',
                        'jobs': [{'_class': job, 'name': 'b', 'url': 'u', 'color': 'blue'}],
                    },
                ]
            }
        )

        names = [i.fullname for i in make(mocker, allowed_folders='Branch-Retail/a').get_items()]

        assert names == ['Branch-Retail', 'Branch-Retail/a']


class TestCaps:
    def test_console_is_capped_and_marked_truncated(self, mocker, mock_session):
        jenkins = make(mocker)
        mock_session.get.return_value = mocker.Mock(iter_lines=lambda decode_unicode: iter(['line'] * 6000))

        out = jenkins.get_build_console_output(fullname='j', number=1).split(chr(10))

        assert len(out) == Jenkins.MAX_CONSOLE_LINES + 1
        assert out[-1].startswith('[output truncated')

    def test_explicit_small_limit_is_not_marked(self, mocker, mock_session):
        mock_session.get.return_value = mocker.Mock(iter_lines=lambda decode_unicode: iter(['line'] * 50))

        out = make(mocker).get_build_console_output(fullname='j', number=1, limit=3)

        assert out == chr(10).join(['line'] * 3)

    def test_long_lines_are_cut(self, mocker, mock_session):
        mock_session.get.return_value = mocker.Mock(iter_lines=lambda decode_unicode: iter(['x' * 5000]))

        assert len(make(mocker).get_build_console_output(fullname='j', number=1)) == Jenkins.MAX_CONSOLE_LINE_CHARS

    def test_overlong_pattern_is_refused(self, mocker):
        with pytest.raises(ValueError, match='pattern is longer'):
            make(mocker).get_build_console_output(fullname='j', number=1, pattern='a' * 201)

    def test_artifact_over_declared_size_is_refused(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(headers={'Content-Length': str(Jenkins.MAX_ARTIFACT_BYTES + 1)})

        with pytest.raises(ValueError, match='byte limit'):
            make(mocker).get_build_artifact(fullname='j', number=1, relative_path='a.zip')

    def test_artifact_over_streamed_size_is_refused(self, mocker, mock_session):
        big = b'x' * (Jenkins.MAX_ARTIFACT_BYTES + 1)
        mock_session.request.return_value = mocker.Mock(headers={}, iter_content=lambda chunk_size: [big])

        with pytest.raises(ValueError, match='byte limit'):
            make(mocker).get_build_artifact(fullname='j', number=1, relative_path='a.zip')


class TestBuildsList:
    def test_list_builds(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(json=lambda: {'builds': [{'number': 3, 'result': 'SUCCESS'}]})

        assert make(mocker).get_builds(fullname='f/j', limit=500) == [{'number': 3, 'result': 'SUCCESS'}]
        assert mock_session.request.call_args.kwargs['url'].endswith(
            'job/f/job/j/api/json?tree=builds[number,url,result,building,timestamp,duration]{0,100}'
        )

    def test_list_builds_empty(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(json=lambda: {})

        assert make(mocker).get_builds(fullname='j') == []


class TestRedaction:
    def test_encrypted_secrets_are_masked(self):
        xml = '<a>{AQAAABAAAAAwq1J1v3m8o2oQwJrEiE0uR0pGq0o9a1f6bW4tZzZ1o9o=}</a>'

        assert redact_config_xml(xml) == '<a>{REDACTED}</a>'

    def test_secret_named_elements_are_masked(self):
        xml = '<password>hunter2</password><apiToken>abc</apiToken><credentialsId>deploy-key</credentialsId>'

        out = redact_config_xml(xml)

        assert 'hunter2' not in out
        assert '>abc<' not in out
        assert '<credentialsId>deploy-key</credentialsId>' in out

    def test_inline_shell_assignments_are_masked_but_variable_refs_kept(self):
        xml = '<command>export DEPLOY_TOKEN=s3cr3t export PASS_API_KEY=$FROM_ENV npm ci</command>'

        out = redact_config_xml(xml)

        assert 's3cr3t' not in out
        assert 'DEPLOY_TOKEN=[REDACTED]' in out
        assert 'PASS_API_KEY=$FROM_ENV' in out
        assert 'npm ci' in out
