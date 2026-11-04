import pytest

from mcp_jenkins.core.lifespan import jenkins, lifespan
from mcp_jenkins.jenkins import Jenkins


class TestLifespan:
    @pytest.fixture(autouse=True, scope='class')
    def mock_jenkins(self, class_mocker):
        class_mocker.patch(
            'mcp_jenkins.core.lifespan.jenkins',
            return_value=Jenkins(
                url='https://jenkins.example.com',
                username='username',
                password='password',
                timeout=5,
                verify_ssl=True,
            ),
        )

    @pytest.mark.asyncio
    async def test_lifespan_context(self, mocker):
        def getenv(key: str, default=None):
            env = {
                'jenkins_url': None,
                'jenkins_username': 'username',
                'jenkins_password': None,
                'jenkins_timeout': '5',
                'jenkins_verify_ssl': 'true',
                'jenkins_session_singleton': 'true',
                'jenkins_allowed_folders': 'Branch-Retail',
            }
            return env.get(key, default)

        mocker.patch('mcp_jenkins.core.lifespan.os', mocker.Mock(getenv=getenv))
        async with lifespan(mocker.Mock) as context:
            assert context.jenkins_url is None
            assert context.jenkins_username == 'username'
            assert context.jenkins_password is None
            assert context.jenkins_timeout == 5
            assert context.jenkins_verify_ssl is True
            assert context.jenkins_session_singleton is True
            assert context.jenkins_allowed_folders == 'Branch-Retail'


class TestJenkins:
    @pytest.fixture(autouse=True)
    def mock_jenkins(self, mocker):
        return mocker.patch('mcp_jenkins.core.lifespan.Jenkins')

    @pytest.fixture
    def make_ctx(self, mocker):
        def make(**overrides: object):
            values = {
                'jenkins_url': 'https://jenkins.example.com',
                'jenkins_username': 'username',
                'jenkins_password': 'password',
                'jenkins_timeout': 5,
                'jenkins_verify_ssl': True,
                'jenkins_allowed_folders': '',
                'jenkins_session_singleton': True,
            }
            values.update(overrides)
            return mocker.Mock(
                request_context=mocker.Mock(lifespan_context=mocker.Mock(**values)),
                session=mocker.Mock(spec=[]),
            )

        return make

    def test_builds_client_from_server_configuration(self, mock_jenkins, make_ctx):
        ctx = make_ctx(jenkins_allowed_folders='Branch-Retail', jenkins_verify_ssl=False)

        result = jenkins(ctx)

        mock_jenkins.assert_called_once_with(
            url='https://jenkins.example.com',
            username='username',
            password='password',
            timeout=5,
            verify_ssl=False,
            allowed_folders='Branch-Retail',
        )
        assert result is ctx.session.jenkins

    def test_client_headers_can_not_replace_url_or_credentials(self, mock_jenkins, make_ctx, mocker):
        # A client-supplied URL/credentials used to override the configured ones; no request is consulted now.
        get_http_request = mocker.patch('fastmcp.server.dependencies.get_http_request')

        jenkins(make_ctx())

        get_http_request.assert_not_called()
        assert mock_jenkins.call_args.kwargs['url'] == 'https://jenkins.example.com'
        assert mock_jenkins.call_args.kwargs['username'] == 'username'

    def test_url_only_creates_anonymous_client(self, mock_jenkins, make_ctx):
        jenkins(make_ctx(jenkins_username=None, jenkins_password=None))

        assert mock_jenkins.call_args.kwargs['username'] is None
        assert mock_jenkins.call_args.kwargs['password'] is None

    def test_empty_credentials_mean_anonymous(self, mock_jenkins, make_ctx):
        jenkins(make_ctx(jenkins_username='', jenkins_password=''))

        mock_jenkins.assert_called_once()

    def test_username_without_password(self, make_ctx):
        with pytest.raises(ValueError, match='incomplete'):
            jenkins(make_ctx(jenkins_password=None))

    def test_password_without_username(self, make_ctx):
        with pytest.raises(ValueError, match='incomplete'):
            jenkins(make_ctx(jenkins_username=None))

    def test_missing_url(self, make_ctx):
        with pytest.raises(ValueError, match='incomplete'):
            jenkins(make_ctx(jenkins_url=None))

    def test_ctx_jenkins_exists(self, mock_jenkins, make_ctx, mocker):
        ctx = make_ctx()
        existing = mocker.Mock()
        ctx.session = mocker.Mock(jenkins=existing)

        assert jenkins(ctx) is existing
        mock_jenkins.assert_not_called()
