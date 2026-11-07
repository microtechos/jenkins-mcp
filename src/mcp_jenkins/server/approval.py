import hashlib
import os

from fastmcp import Context
from loguru import logger
from mcp.types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult

# First protocol version that has no server-initiated requests (SEP-2322 / SEP-2575). ISO dates compare as strings.
_MODERN_ERA = '2026-07-28'
_APPROVAL_KEY = 'approve'
_APPROVAL_SCHEMA = {
    'type': 'object',
    'properties': {'value': {'type': 'boolean', 'title': 'Approve'}},
    'required': ['value'],
}


def _protocol_version(ctx: Context) -> str | None:
    try:
        return getattr(ctx.request_context, 'protocol_version', None)
    except Exception:  # noqa: BLE001 - no active request: treat as the classic path
        return None


def _is_modern(ctx: Context) -> bool:
    """True on a 2026-07-28 or newer connection, which cannot send `elicitation/create` to the client.

    There the server asks by returning an InputRequiredResult and the client retries the call with the answer.
    Older FastMCP versions have no `input_responses`, so they always take the classic path.
    """
    version = _protocol_version(ctx)
    return bool(version) and version >= _MODERN_ERA and hasattr(ctx, 'input_responses')


def _bind_token(bind: str) -> str:
    return hashlib.sha256(f'approval|{bind}'.encode()).hexdigest()


def _refused() -> PermissionError:
    return PermissionError('Not approved: the action was declined or cancelled')


def _cannot_ask() -> PermissionError:
    msg = (
        'This client cannot ask you to approve the action, so it was not run. '
        'Do it in Jenkins, or start the server with --no-require-approval'
    )
    return PermissionError(msg)


async def require_approval(ctx: Context, message: str, bind: str = '') -> InputRequiredResult | None:
    """Ask the user, through the client, to approve one confirmed write before it is sent to Jenkins.

    This makes `confirm=true` a human decision instead of something a model can set on its own, for example
    after reading text planted in a build log. If the client cannot ask the action is refused. Turn it off only
    deliberately, with --no-require-approval.

    Two ways to ask, by protocol era:
    - Classic (handshake) connections: an `elicitation/create` request, answered in this same call; returns None.
    - 2026-07-28 and newer: the server cannot send requests, so the first leg returns an InputRequiredResult that
      the tool must return as its result; the client shows the prompt and calls the tool again with the answer. On
      that second leg this returns None when approved. `bind` names what was asked (job, digest); the retry is
      refused if it no longer matches, so an answer for one action can not approve another.

    Returns:
        None when approved (go on), or an InputRequiredResult the tool must return unchanged to ask the user.

    Raises:
        PermissionError: If the user declined, cancelled, or the client could not ask.
    """
    if os.environ.get('jenkins_require_approval', 'true').lower() != 'true':
        return None

    modern = _is_modern(ctx)
    logger.debug(f'Approval requested: protocol {_protocol_version(ctx)!r}, path {"modern" if modern else "classic"}')
    if modern:
        return _approve_modern(ctx, message, bind)

    try:
        result = await ctx.elicit(message, response_type=bool)
    except Exception as e:  # noqa: BLE001 - any failure to ask must fail closed
        raise _cannot_ask() from e

    if getattr(result, 'action', None) != 'accept' or getattr(result, 'data', None) is not True:
        raise _refused()
    return None


def _approve_modern(ctx: Context, message: str, bind: str) -> InputRequiredResult | None:
    token = _bind_token(bind)
    answer = (ctx.input_responses or {}).get(_APPROVAL_KEY)

    if answer is None:
        logger.debug('Approval: asking the client with an InputRequiredResult')
        request = ElicitRequest(params=ElicitRequestFormParams(message=message, requested_schema=_APPROVAL_SCHEMA))
        return InputRequiredResult(input_requests={_APPROVAL_KEY: request}, request_state=token)

    if ctx.request_state != token:
        msg = 'Not approved: the action changed after the approval prompt was shown'
        raise PermissionError(msg)
    accepted = isinstance(answer, ElicitResult) and answer.action == 'accept'
    if not accepted or (answer.content or {}).get('value') is not True:
        raise _refused()
    logger.debug('Approval: accepted')
    return None


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
