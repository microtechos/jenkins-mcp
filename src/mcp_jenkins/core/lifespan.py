import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict

from mcp_jenkins.jenkins import Jenkins


class LifespanContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    jenkins_url: str | None
    jenkins_username: str | None
    jenkins_password: str | None
    jenkins_timeout: int = 5
    jenkins_verify_ssl: bool = True
    jenkins_allowed_folders: str = ''

    jenkins_session_singleton: bool = True


@asynccontextmanager
async def lifespan(app: FastMCP[LifespanContext]) -> AsyncIterator['LifespanContext']:
    jenkins_url = os.getenv('jenkins_url')
    jenkins_username = os.getenv('jenkins_username')
    jenkins_password = os.getenv('jenkins_password')

    jenkins_timeout = int(os.getenv('jenkins_timeout', '5'))
    jenkins_verify_ssl = os.getenv('jenkins_verify_ssl', 'true').lower() == 'true'
    jenkins_session_singleton = os.getenv('jenkins_session_singleton', 'true').lower() == 'true'
    jenkins_allowed_folders = os.getenv('jenkins_allowed_folders', '')

    yield LifespanContext(
        jenkins_url=jenkins_url,
        jenkins_username=jenkins_username,
        jenkins_password=jenkins_password,
        jenkins_timeout=jenkins_timeout,
        jenkins_verify_ssl=jenkins_verify_ssl,
        jenkins_allowed_folders=jenkins_allowed_folders,
        jenkins_session_singleton=jenkins_session_singleton,
    )


def jenkins(ctx: Context) -> Jenkins:
    """Return the session's Jenkins client, built only from the server's own configuration.

    The URL and credentials come from the CLI/environment and nothing a client sends can replace them,
    so the configured credentials are only ever presented to the configured Jenkins.
    """
    lifespan_context = ctx.request_context.lifespan_context

    if lifespan_context.jenkins_session_singleton and getattr(ctx.session, 'jenkins', None):
        return ctx.session.jenkins

    jenkins_url = lifespan_context.jenkins_url
    jenkins_username = lifespan_context.jenkins_username
    jenkins_password = lifespan_context.jenkins_password

    # Exactly one of username/password is almost always a config typo, so it fails instead of going anonymous.
    if not jenkins_url or bool(jenkins_username) != bool(jenkins_password):
        msg = (
            'Jenkins connection details are incomplete: the URL is required, '
            'and username and password must be provided together or not at all. '
            'Please provide them via --jenkins-url, --jenkins-username and --jenkins-password '
            '(or the JENKINS_URL, JENKINS_USERNAME and JENKINS_PASSWORD environment variables).'
        )
        raise ValueError(msg)

    ctx.session.jenkins = Jenkins(
        url=jenkins_url,
        username=jenkins_username,
        password=jenkins_password,
        timeout=lifespan_context.jenkins_timeout,
        verify_ssl=lifespan_context.jenkins_verify_ssl,
        allowed_folders=lifespan_context.jenkins_allowed_folders,
    )

    return ctx.session.jenkins
