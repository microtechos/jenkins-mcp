# Security Policy

This is Microtech's fork of `lanbaoshen/mcp-jenkins`: read-only by default, with three opt-in tools that can start,
stop and cancel release builds.

## Supported versions

Only the latest tag of this fork is supported.

## Reporting a vulnerability

Do not open a public issue. Report it privately to the Microtech dev team (the maintainers of the
`microtech-jenkins` plugin in `microtechos/claude-ai-agent-system`) with the affected version, how to
reproduce it and the impact. Expect an acknowledgement within a few working days.

## Design rules that must not regress

- The only tools that send a non-GET request are `trigger_build`, `stop_build` and `cancel_queue_item`: they are not registered unless the server is started with `--allow-trigger`, `trigger_build` acts only on the exact jobs in `--trigger-jobs`, and `stop_build` and `cancel_queue_item` on those plus the jobs in `--stop-jobs` (a queue item is read first and refused unless its job is listed), and they do nothing without `confirm=true`. No tool runs scripts.
- A confirmed start, stop or cancel asks the user through the client first (`--require-approval`, default on, changeable only
  by the command-line flag, never by an environment variable) and is refused when the client cannot ask. The start prompt
  shows the branch, default parameters and downstream jobs, and the start is refused if the job changed after the dry
  run. Every confirmed write and every failed attempt is appended to the audit file, and starts are capped per session
  (a start counts even if the reply is lost).
- Only stdio is supported; no network listener.
- The Jenkins URL and credentials come only from the server's own configuration.
- Job names, node names and artifact paths are validated and URL-quoted before use. User regular expressions are
  length-capped and refused when they nest or alternate repeats (they would run on the event loop).
- Output is size-capped (console lines, artifacts, listings, views and plugin depth). Config, console output, build scripts,
  build parameters, parameter defaults, test reports and pending inputs are redacted of secret-looking values: best effort,
  not a guarantee, and bounded in work (2 MB). Views are returned as names, urls and colours only, and unknown job types never
  return their properties or actions.
- Reads of the queue, running builds, nodes and plugins are not scoped to `--allowed-folders`; items, queries, job status
  and views are.
- The server does not log request URLs below INFO level, and refuses a Jenkins URL that embeds credentials.

## What this server cannot protect

The Jenkins account it runs with is the real boundary: the server's allowlist and approval prompt do not limit what that
account's token can do if something else uses it (the plugin's token is stored by Claude Code in a file under the user
profile). Use a dedicated least-privilege Jenkins account and keep Job/Configure on the release jobs tight.

Settings that are not locked by the server are inherited from the environment of whoever starts it: `JENKINS_VERIFY_SSL`,
`JENKINS_MAX_STARTS`, `JENKINS_AUDIT_LOG`, `JENKINS_TIMEOUT`. The launcher (the plugin's `.mcp.json`) should pin them.
