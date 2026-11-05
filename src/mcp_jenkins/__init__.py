import asyncio
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from loguru import logger

# Quiet by default: request URLs are not written to the MCP log at DEBUG level.
logger.remove()
logger.add(sys.stderr, level='INFO')

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _load_env_file(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:  # noqa: ARG001
    # Eager so JENKINS_* variables from the file are visible to the other options' envvar lookups below.
    # Only an explicit --env-file is read: a .env found in the working directory is never loaded, so a stray
    # file can not silently supply credentials or point the server at another Jenkins.
    if value:
        load_dotenv(dotenv_path=value)
    return value


@click.command()
@click.option(
    '--env-file',
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    is_eager=True,
    expose_value=False,
    callback=_load_env_file,
    help='Path to a .env file to load configuration from. Nothing is loaded unless this is given.',
)
@click.option('--jenkins-url', required=False, envvar='JENKINS_URL')
@click.option('--jenkins-username', required=False, envvar='JENKINS_USERNAME')
@click.option('--jenkins-password', required=False, envvar='JENKINS_PASSWORD')
@click.option('--jenkins-timeout', default=5, envvar='JENKINS_TIMEOUT')
@click.option(
    '--jenkins-verify-ssl/--no-jenkins-verify-ssl',
    default=True,
    envvar='JENKINS_VERIFY_SSL',
    help='Whether to verify SSL certificates, default is True',
)
@click.option(
    '--allowed-folders',
    default='',
    envvar='JENKINS_ALLOWED_FOLDERS',
    help='Comma-separated list of folder/job full names this server may read (e.g. "Branch-Retail,Branch-Salon"). '
    'Empty means no restriction. Job reads outside the list are refused and listings are filtered.',
)
@click.option(
    '--allow-trigger/--no-allow-trigger',
    default=False,
    envvar='JENKINS_ALLOW_TRIGGER',
    help='Register trigger_build, stop_build and cancel_queue_item, the only tools that write. Off by default.',
)
@click.option(
    '--trigger-jobs',
    default='',
    envvar='JENKINS_TRIGGER_JOBS',
    help='Comma-separated exact job full names trigger_build may start. Empty = none can be started.',
)
@click.option(
    '--stop-jobs',
    default='',
    envvar='JENKINS_STOP_JOBS',
    help='Comma-separated exact job full names that stop_build and cancel_queue_item may also act on '
    '(for example the rest of a release chain). They can never be started by trigger_build.',
)
@click.option(
    '--require-approval/--no-require-approval',
    default=True,
    help='Ask the user (MCP elicitation) before any confirmed start, stop or cancel. Default on; if the client '
    'cannot ask, the action is refused. Command-line only: an environment variable can not switch it off.',
)
@click.option(
    '--audit-log',
    default='',
    envvar='JENKINS_AUDIT_LOG',
    help='JSONL file recording every confirmed start, stop and cancel. Default with --allow-trigger: '
    '~/.microtech/jenkins-mcp-audit.jsonl.',
)
@click.option(
    '--max-starts',
    default=5,
    envvar='JENKINS_MAX_STARTS',
    help='Maximum confirmed trigger_build starts per server session. Default 5.',
)
@click.option(
    '--read-only',
    default=True,
    is_flag=True,
    hidden=True,
    help='Deprecated and ignored: the write tools exist only with --allow-trigger.',
)
@click.option(
    '--tool-regex',
    default='',
    hidden=True,
    help='(Deprecated) Regex pattern to enable specific tools',
)
@click.option(
    '--jenkins-session-singleton/--no-jenkins-session-singleton',
    default=True,
    help='In the same session, does it share the Jenkins request instance, '
    'significantly reducing the number of instantiations',
)
@click.option(
    '--transport',
    type=click.Choice(['stdio']),
    default='stdio',
    help='Only stdio is supported: the server is never exposed on a network port.',
)
def main(
    jenkins_url: str,
    jenkins_username: str,
    jenkins_password: str,
    jenkins_timeout: int,
    jenkins_verify_ssl: bool,  # noqa: FBT001
    allowed_folders: str,
    allow_trigger: bool,  # noqa: FBT001
    trigger_jobs: str,
    stop_jobs: str,
    require_approval: bool,  # noqa: FBT001
    audit_log: str,
    max_starts: int,
    read_only: bool,  # noqa: ARG001, FBT001
    tool_regex: str,
    jenkins_session_singleton: bool,  # noqa: FBT001
    transport: str,
) -> None:
    if jenkins_url:
        os.environ['jenkins_url'] = jenkins_url
    if jenkins_username:
        os.environ['jenkins_username'] = jenkins_username
    if jenkins_password:
        os.environ['jenkins_password'] = jenkins_password

    os.environ['jenkins_timeout'] = str(jenkins_timeout)
    os.environ['jenkins_verify_ssl'] = str(jenkins_verify_ssl).lower()
    os.environ['jenkins_session_singleton'] = str(jenkins_session_singleton).lower()
    os.environ['jenkins_allowed_folders'] = allowed_folders
    os.environ['jenkins_allow_trigger'] = str(allow_trigger).lower()
    os.environ['jenkins_trigger_jobs'] = trigger_jobs
    os.environ['jenkins_stop_jobs'] = stop_jobs
    os.environ['jenkins_require_approval'] = str(require_approval).lower()
    if allow_trigger and not audit_log:
        audit_log = str(Path.home() / '.microtech' / 'jenkins-mcp-audit.jsonl')
    os.environ['jenkins_audit_log'] = audit_log
    os.environ['jenkins_max_starts'] = str(max_starts)

    from mcp_jenkins.server import mcp

    if tool_regex:
        logger.warning('The [--tool-regex] option is deprecated and ignored.')

    asyncio.run(mcp.run_async(transport=transport))


if __name__ == '__main__':
    main()
