# Security Policy

This is Microtech's read-only fork of `lanbaoshen/mcp-jenkins`.

## Supported versions

Only the latest tag of this fork is supported.

## Reporting a vulnerability

Do not open a public issue. Report it privately to the Microtech dev team (the maintainers of the
`microtech-jenkins` plugin in `microtechos/claude-ai-agent-system`) with the affected version, how to
reproduce it and the impact. Expect an acknowledgement within a few working days.

## Design rules that must not regress

- No tool sends a non-GET request to Jenkins and no tool runs scripts.
- Only stdio is supported; no network listener.
- The Jenkins URL and credentials come only from the server's own configuration.
- Job names, node names and artifact paths are validated and URL-quoted before use.
- Output is size-capped, and `get_item_config` redacts secret-looking values.
