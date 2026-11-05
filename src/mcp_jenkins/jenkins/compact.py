"""Compact, bounded views of Jenkins data, so one tool call does not flood a model's context.

Pure functions: no network, no Jenkins client. The server tools call them on what the client returned.
"""

import xml.etree.ElementTree as ET

from mcp_jenkins.jenkins.redact import redact_config_xml

ALLOWED_FIELDS = ('fullname', 'name', 'kind', 'class_', 'url', 'color')
DEFAULT_FIELDS = ('fullname', 'kind', 'color')
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

_COMMAND_CHARS = 600
_DESCRIPTION_CHARS = 200


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _truncation_marker(shown: int, total: int) -> dict:
    return {
        'truncated': True,
        'shown': shown,
        'total': total,
        'hint': f'narrow with fullname_pattern / folder_depth, or raise limit (max {MAX_LIMIT})',
    }


def compact_items(items: list, *, fields: list[str] | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Project listing items to a few fields and cap the count.

    Nested ``jobs`` of folders are never included: every child is already listed as its own item.

    Args:
        items: Item models (with class_, name, url, fullname and, for jobs, color).
        fields: Fields to keep, from ALLOWED_FIELDS. Default: fullname, kind, color.
        limit: Maximum number of items (1-MAX_LIMIT). A marker row is appended when items were dropped.

    Returns:
        One dict per item, plus a truncation marker row when the list was cut.

    Raises:
        ValueError: If a requested field is not allowed.
    """
    chosen = tuple(fields) if fields else DEFAULT_FIELDS
    unknown = [f for f in chosen if f not in ALLOWED_FIELDS]
    if unknown:
        msg = f'Unknown field(s) {unknown}; allowed: {", ".join(ALLOWED_FIELDS)}'
        raise ValueError(msg)

    limit = _clamp_limit(limit)
    rows = []
    for item in items[:limit]:
        row = {}
        for field in chosen:
            value = item.class_.rsplit('.', 1)[-1] if field == 'kind' else getattr(item, field, None)
            if value is not None:
                row[field] = value
        rows.append(row)

    if len(items) > limit:
        rows.append(_truncation_marker(limit, len(items)))
    return rows


def compact_rows(rows: list[dict], *, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Cap a list of already-compact dict rows and append a marker when rows were dropped."""
    limit = _clamp_limit(limit)
    out = list(rows[:limit])
    if len(rows) > limit:
        out.append(_truncation_marker(limit, len(rows)))
    return out


def _short(tag: str) -> str:
    return tag.rsplit('.', 1)[-1]


def _clip(text: str | None, size: int) -> str:
    text = (text or '').strip()
    return text if len(text) <= size else f'{text[:size]}...(+{len(text) - size} chars)'


def summarize_config(config_xml: str) -> dict:
    """Summarise a job's config.xml: repo and branch, steps, triggers, parameters and downstream jobs.

    Secret-looking values are redacted first, and credential ids, wrapper settings and long scripts are not
    reproduced, so the summary is a fraction of the raw file.
    """
    root = ET.fromstring(redact_config_xml(config_xml))  # noqa: S314 - config comes from our own Jenkins
    summary: dict = {'kind': _short(root.tag), 'disabled': (root.findtext('disabled') or '').strip() == 'true'}

    description = _clip(root.findtext('description'), _DESCRIPTION_CHARS)
    if description:
        summary['description'] = description
    for key in ('jdk', 'goals', 'mavenName', 'assignedNode'):
        value = (root.findtext(key) or '').strip()
        if value and value != '(System)':
            summary[key] = value
    root_module = root.find('rootModule')
    if root_module is not None:
        summary['module'] = f'{root_module.findtext("groupId")}:{root_module.findtext("artifactId")}'

    urls = []
    for remote in root.iter('hudson.plugins.git.UserRemoteConfig'):
        url = (remote.findtext('url') or '').strip()
        if url:
            urls.append(url)
    branches = []
    for spec in root.iter('hudson.plugins.git.BranchSpec'):
        name = (spec.findtext('name') or '').strip()
        if name:
            branches.append(name)
    if urls or branches:
        summary['scm'] = {'urls': urls, 'branches': branches}

    parameters = []
    for definitions in root.iter('parameterDefinitions'):
        for definition in definitions:
            parameters.append(
                {
                    'name': (definition.findtext('name') or '').strip(),
                    'type': _short(definition.tag),
                    'default': _clip(definition.findtext('defaultValue'), 80),
                }
            )
    if parameters:
        summary['parameters'] = parameters

    triggers = root.find('triggers')
    if triggers is not None and len(triggers):
        summary['triggers'] = [_short(t.tag) for t in triggers]

    steps = []
    for phase in ('prebuilders', 'builders', 'postbuilders'):
        container = root.find(phase)
        for step in container if container is not None else []:
            entry = {'phase': phase, 'type': _short(step.tag)}
            command = step.findtext('command')
            if command:
                entry['command'] = _clip(command, _COMMAND_CHARS)
            steps.append(entry)
    if steps:
        summary['steps'] = steps

    downstream = []
    for element in root.iter('childProjects'):
        downstream += [p.strip() for p in (element.text or '').split(',') if p.strip()]
    for element in root.iter('hudson.plugins.parameterizedtrigger.BuildTriggerConfig'):
        downstream += [p.strip() for p in (element.findtext('projects') or '').split(',') if p.strip()]
    if downstream:
        summary['downstream'] = downstream

    wrappers = root.find('buildWrappers')
    if wrappers is not None and len(wrappers):
        summary['wrappers'] = [_short(w.tag) for w in wrappers]

    if summary['kind'] == 'flow-definition':
        script = root.find('.//script')
        if script is not None:
            summary['pipelineScriptChars'] = len(script.text or '')
    return summary
