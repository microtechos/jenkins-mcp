# Security Policy

This is Microtech's read-only fork of `lanbaoshen/mcp-jenkins`.

## Supported versions

Only the latest tag of this fork is supported.

## Reporting a vulnerability

Do not open a public issue. Report it privately to the Microtech dev team (the maintainers of the
`microtech-jenkins` plugin in `microtechos/claude-ai-agent-system`) with the affected version, how to
reproduce it and the impact. Expect an acknowledgement within a few working days.

## Design rules that must not regress

- The only tools that send a non-GET request are `trigger_build`, `stop_build` and `cancel_queue_item`: they are not registered unless the server is started with `--allow-trigger`, `trigger_build` acts only on the exact jobs in `--trigger-jobs`, and `stop_build` and `cancel_queue_item` on those plus the jobs in `--stop-jobs` (a queue item is read first and refused unless its job is listed), and they do nothing without `confirm=true`. No tool runs scripts.
- Only stdio is supported; no network listener.
- The Jenkins URL and credentials come only from the server's own configuration.
- Job names, node names and artifact paths are validated and URL-quoted before use.
- Output is size-capped, and `get_item_config` redacts secret-looking values.
