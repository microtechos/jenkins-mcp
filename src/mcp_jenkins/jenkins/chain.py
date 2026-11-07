"""Where is a release chain? One compact, read-only answer for an entry build and its downstream jobs.

A release starts one entry job; Jenkins then starts the next jobs by itself. This module follows one entry build
through an ordered list of expected chain jobs and says whether the chain passed, failed, was aborted, is still
running or is waiting for the next job. It only reads: every request is a GET on a job's `api/json`.

A build of a chain job belongs to the entry build when one of its causes names an already attributed build as its
upstream. When a job's builds carry no cause information at all (older plugins, trimmed API output) the oldest such
build started at or after the entry build is used instead, and `attribution` says so.
"""

import time

from requests.exceptions import HTTPError

from mcp_jenkins.jenkins import Jenkins

MAX_CHAIN_JOBS = 30
MAX_NAME_LENGTH = 200
WINDOW = 15  # builds read per chain job
ENTRY_WINDOW = 25  # builds read from the entry job to find the entry build
TERMINAL = ('passed', 'failed', 'aborted')

_BUILD_FIELDS = 'number,result,building,timestamp,duration'
_CAUSES = 'actions[causes[upstreamProject,upstreamBuild]]'


def _builds_tree(limit: int) -> str:
    return f'buildable,inQueue,builds[{_BUILD_FIELDS},{_CAUSES}]{{0,{limit}}}'


_STATE_BY_RESULT = {
    'SUCCESS': 'success',
    'FAILURE': 'failed',
    'ABORTED': 'aborted',
    'UNSTABLE': 'unstable',
    'NOT_BUILT': 'aborted',  # skipped: the build did not complete
}


def _check_name(name: object, *, what: str) -> str:
    """A plain job fullname: text, bounded, and without anything that could change where a request lands."""
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME_LENGTH:
        msg = f'Invalid {what}: expected a job fullname of at most {MAX_NAME_LENGTH} characters'
        raise ValueError(msg)
    return name.strip().strip('/')


def _get_json(client: Jenkins, path_and_query: str, *, missing: str) -> dict:
    try:
        return client.request('GET', path_and_query).json()
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            raise ValueError(missing) from e
        raise


def _builds(client: Jenkins, fullname: str, limit: int) -> dict:
    job_path = client._job_path(fullname)  # noqa: SLF001 - same package; keeps folder allowlist and name checks
    data = _get_json(
        client,
        f'{job_path}/api/json?tree={_builds_tree(limit)}',
        missing=f'Job not found: {fullname}',
    )
    if 'buildable' not in data:
        msg = f'{fullname} cannot have builds (a folder or multibranch parent?), pass a job fullname'
        raise ValueError(msg)
    return data


def _entry_build(client: Jenkins, entry: str, number: int | None) -> dict:
    data = _builds(client, entry, ENTRY_WINDOW)
    builds = data.get('builds') or []
    if number is None:
        if not builds:
            msg = f'No build found for job: {entry}'
            raise ValueError(msg)
        return builds[0]
    for build in builds:
        if build.get('number') == number:
            return build

    job_path = client._job_path(entry)  # noqa: SLF001
    return _get_json(
        client,
        f'{job_path}/{int(number)}/api/json?tree={_BUILD_FIELDS},{_CAUSES}',
        missing=f'No build #{number} of {entry}',
    )


def _upstreams(build: dict) -> set[tuple[str, int]]:
    found = set()
    for action in build.get('actions') or []:
        for cause in (action or {}).get('causes') or []:
            project, number = cause.get('upstreamProject'), cause.get('upstreamBuild')
            if project is not None and number is not None:
                found.add((str(project).strip('/'), int(number)))
    return found


def _has_causes(build: dict) -> bool:
    return any((action or {}).get('causes') for action in build.get('actions') or [])


def _state(build: dict) -> str:
    if build.get('building') or build.get('result') is None:
        return 'running'
    return _STATE_BY_RESULT.get(build['result'], 'failed')


def _duration_ms(build: dict, now_ms: int) -> int | None:
    if build.get('building') or build.get('result') is None:
        started = build.get('timestamp')
        return max(0, now_ms - started) if started else None
    return build.get('duration')


def _row(job: str, build: dict | None, now_ms: int, *, queued: bool = False) -> dict:
    if build is None:
        return {'job': job, 'number': None, 'state': 'queued' if queued else 'notstarted', 'durationMs': None}
    return {
        'job': job,
        'number': build.get('number'),
        'state': _state(build),
        'durationMs': _duration_ms(build, now_ms),
    }


def _short(job: str) -> str:
    return job.rsplit('/', 1)[-1]


def _minutes(ms: int | None) -> str:
    return f'{round((ms or 0) / 60000)} min'


def chain_status(
    client: Jenkins, *, entry: str, entry_number: int | None = None, chain: list[str] | None = None
) -> dict:
    """Read the entry build and the chain jobs once and say where the chain stands.

    Args:
        client: The `Jenkins` REST client.
        entry: Fullname of the entry job.
        entry_number: The entry build to follow; None follows the latest build.
        chain: Ordered fullnames of the downstream jobs expected after the entry job (the entry job itself may be
            listed first; it is not counted twice). None or empty follows the entry job alone.

    Returns:
        verdict (passed | failed | aborted | running | waiting), stoppedAt, runningAt, finalJob, attribution
        (how builds were matched: upstream and/or time), rows (job, number, state, durationMs) and a one-line summary.
    """
    entry = _check_name(entry, what='entry')
    names = [_check_name(name, what='chain job') for name in (chain or [])]
    if len(names) > MAX_CHAIN_JOBS:
        msg = f'A chain has at most {MAX_CHAIN_JOBS} jobs, got {len(names)}'
        raise ValueError(msg)
    if entry_number is not None and (isinstance(entry_number, bool) or int(entry_number) < 1):
        msg = 'entry_number must be a positive build number'
        raise ValueError(msg)
    jobs = [name for name in dict.fromkeys(names) if name != entry]
    for name in (entry, *jobs):  # refuse unsafe names and names outside the allowed folders before any request
        client._job_path(name)  # noqa: SLF001

    now_ms = int(time.time() * 1000)
    entry_build = _entry_build(client, entry, entry_number)
    started = entry_build.get('timestamp') or 0
    attributed: dict[tuple[str, int], dict] = {(entry, entry_build['number']): entry_build}
    rows = [_row(entry, entry_build, now_ms)]
    methods: set[str] = set()

    for job in jobs:
        data = _builds(client, job, WINDOW)
        # newest first from Jenkins; only builds that began after the entry build can belong to it
        candidates = [b for b in data.get('builds') or [] if (b.get('timestamp') or 0) >= started]
        by_cause = [b for b in candidates if _upstreams(b) & set(attributed)]
        chosen, method = None, None
        if by_cause:
            chosen, method = by_cause[0], 'upstream'  # newest build caused by an attributed build
        else:
            uncaused = [b for b in candidates if not _has_causes(b)]
            if uncaused:
                chosen, method = uncaused[-1], 'time'  # oldest build with no cause information
        if chosen is not None:
            attributed[(job, chosen['number'])] = chosen
            methods.add(method)
        rows.append(_row(job, chosen, now_ms, queued=chosen is None and bool(data.get('inQueue'))))

    final_job = jobs[-1] if jobs else entry
    final_build = attributed.get((final_job, rows[-1]['number']))
    finished = (
        (final_build['timestamp'] + (final_build.get('duration') or 0) - started) if final_build and started else None
    )
    return _verdict(
        rows, final_job=final_job, entry_start=started, attribution=sorted(methods), now_ms=now_ms, total_ms=finished
    )


def _verdict(
    rows: list[dict], *, final_job: str, entry_start: int, attribution: list[str], now_ms: int, total_ms: int | None
) -> dict:
    stop = next((r for r in rows if r['state'] in ('failed', 'aborted', 'unstable')), None)
    running = next((r for r in rows if r['state'] == 'running'), None)
    done = sum(1 for r in rows if r['state'] == 'success')
    final = rows[-1]
    elapsed = _minutes(now_ms - entry_start) if entry_start else '?'

    if stop is not None:
        verdict = 'aborted' if stop['state'] == 'aborted' else 'failed'
        result = {'failed': 'FAILURE', 'aborted': 'ABORTED', 'unstable': 'UNSTABLE'}[stop['state']]
        summary = f'stopped at {_short(stop["job"])} #{stop["number"]} {result}'
    elif final['state'] == 'success':
        verdict = 'passed'
        summary = f'passed through {_short(final["job"])} #{final["number"]} in {_minutes(total_ms)}'
    elif running is not None:
        verdict = 'running'
        summary = f'running at {_short(running["job"])} #{running["number"]} ({done} of {len(rows)} done, {elapsed})'
    else:
        verdict = 'waiting'
        upcoming = next((r for r in rows if r['state'] in ('notstarted', 'queued')), rows[-1])
        last_done = next((r for r in reversed(rows) if r['state'] == 'success'), None)
        after = f' after {_short(last_done["job"])} #{last_done["number"]}' if last_done else ''
        summary = (
            f'waiting for {_short(upcoming["job"])} to {"run" if upcoming["state"] == "queued" else "start"}{after}'
        )

    return {
        'verdict': verdict,
        'stoppedAt': stop['job'] if stop else None,
        'runningAt': running['job'] if running else None,
        'finalJob': final_job,
        'attribution': attribution,
        'rows': rows,
        'summary': summary,
    }
