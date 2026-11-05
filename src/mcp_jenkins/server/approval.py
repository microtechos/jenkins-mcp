import os

from fastmcp import Context


async def require_approval(ctx: Context, message: str) -> None:
    """Ask the user, through the client, to approve one confirmed write before it is sent to Jenkins.

    This makes `confirm=true` a human decision instead of something a model can set on its own, for example
    after reading text planted in a build log. If the client cannot ask (no elicitation support) the action is
    refused. Turn it off only deliberately, with --no-require-approval.

    Raises:
        PermissionError: If the user declined, cancelled, or the client could not ask.
    """
    if os.environ.get('jenkins_require_approval', 'true').lower() != 'true':
        return

    try:
        result = await ctx.elicit(message, response_type=bool)
    except Exception as e:  # noqa: BLE001 - any failure to ask must fail closed
        msg = (
            'This client cannot ask you to approve the action, so it was not run. '
            'Do it in Jenkins, or start the server with --no-require-approval'
        )
        raise PermissionError(msg) from e

    if getattr(result, 'action', None) != 'accept' or getattr(result, 'data', None) is not True:
        msg = 'Not approved: the action was declined or cancelled'
        raise PermissionError(msg)


_MAX_LISTED = 12


def _list(items: list[str]) -> str:
    shown = ', '.join(items[:_MAX_LISTED])
    return shown + (f' (+{len(items) - _MAX_LISTED} more)' if len(items) > _MAX_LISTED else '')


def start_message(plan: dict) -> str:
    """What the user is asked to approve: the job and what it will run (branch, default parameters, downstream)."""
    lines = [f'Start a build of {plan["job"]}? It may deploy to production.']
    if plan.get('branches'):
        lines.append(f'Branch: {_list(plan["branches"])}')
    if plan.get('parameters'):
        defaults = [f'{p.get("name")}={p.get("default", "")}' for p in plan['parameters']]
        lines.append(f'Default parameters: {_list(defaults)}')
    if plan.get('downstream'):
        lines.append(f'Then starts: {_list(plan["downstream"])}')
    if plan.get('contextDigest') is None:
        lines.append('(The job configuration could not be read, so what it runs is not shown.)')
    return '\n'.join(lines)
