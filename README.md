# jenkins-mcp (Microtech fork)

Microtech fork of [lanbaoshen/mcp-jenkins](https://github.com/lanbaoshen/mcp-jenkins) (MIT), a Model
Context Protocol server that lets an AI assistant read a Jenkins instance. Upstream version `3.6.0`
(commit `1d8587e`) is the baseline; this fork is **read-only by default** and has three opt-in write tools, all limited to an allowlist of release jobs: `trigger_build`, `stop_build`, `cancel_queue_item`.

It is the transport behind the `microtech-jenkins` plugin in the `microtech-hub` marketplace. End users
do not run it by hand: the plugin's `.mcp.json` starts it and supplies the credentials.

## What differs from upstream

| Area | Upstream | This fork | Why |
| --- | --- | --- |---|
| Other write tools (`submit_input`, `set_item_config`, `set_node_config`) | Present, hidden by `--read-only` | Deleted | A flag can be forgotten or regress; deleted code can not run |
| Starting, stopping, cancelling | `build_item`, `stop_build`, `cancel_queue_item`: any job | `trigger_build`, `stop_build`, `cancel_queue_item`: off by default; with `--allow-trigger` only the exact jobs in `--trigger-jobs` (a queue item is checked against its job first); dry run unless `confirm=true`; parameterised jobs use their defaults | Release automation can start, and undo, the release jobs and nothing else |
| `run_groovy_script` | Present | Deleted | It is code execution on the Jenkins controller |
| `get_node_config` | Present | Deleted | Node configs carry agent connection details and are not needed |
| Transports | stdio, SSE, streamable-http (binds `0.0.0.0`, no auth) | stdio only | Nothing is ever exposed on a network port |
| URL / credentials | A request header could replace the URL while the server's credentials were still sent | Taken only from the server's own configuration | A caller could aim your token at a host of its choice |
| `.env` | Auto-loaded from the working directory | Only with an explicit `--env-file` | A stray file can not silently change credentials |
| Job and artifact paths | Inserted into URLs unchecked | Segments validated and URL-quoted; `..`, `?`, `#`, `%`, `\`, control characters refused | Stops a crafted name reaching other URLs |
| Scope | Whole instance | Optional `--allowed-folders` | Limit reads to the folders you care about |
| Output size | Unbounded | Console 5000 lines, 2000 chars per line, regex up to 200 chars, artifacts 5 MiB | One call can not flood a model's context |
| `get_item_config` | Raw `config.xml` | Secret-looking values replaced by `[REDACTED]` (best effort) | Config files can hold tokens |
| File logging | Wrote the URL and username to `~/.mcp_jenkins/log.log` | None | No credentials metadata on disk |
| `list_builds` | Missing | Added | Build history of a job, newest first |
| Dependencies | Lockfile with advisories | Refreshed lockfile | |

`--read-only` is still accepted and ignored, so existing configurations keep working.

## Run

```
uvx --from git+https://github.com/microtechos/jenkins-mcp@<tag-or-sha> mcp-jenkins --transport stdio
```

| Option | Environment variable | Meaning |
| --- | --- | --- |
| `--jenkins-url` | `JENKINS_URL` | Jenkins base URL (required) |
| `--jenkins-username` | `JENKINS_USERNAME` | User. Give both username and password, or neither (anonymous) |
| `--jenkins-password` | `JENKINS_PASSWORD` | API token (preferred) or password |
| `--jenkins-timeout` | `JENKINS_TIMEOUT` | Seconds per request, default 5 |
| `--jenkins-verify-ssl/--no-jenkins-verify-ssl` | `JENKINS_VERIFY_SSL` | TLS verification, default on |
| `--allow-trigger` | `JENKINS_ALLOW_TRIGGER` | Register `trigger_build`, `stop_build` and `cancel_queue_item` (default off) |
| `--trigger-jobs` | `JENKINS_TRIGGER_JOBS` | Comma-separated exact job full names the three tools may act on. Empty = none |
| `--allowed-folders` | `JENKINS_ALLOWED_FOLDERS` | Comma-separated folder/job full names that may be read, e.g. `Branch-Retail,Branch-Salon`. Empty = no restriction |
| `--env-file` | | Load the settings above from a file (never auto-discovered) |

The allowlist gates every tool that takes a job `fullname` and filters `get_all_items` / `query_items`
(parent folders stay visible so the tree can be navigated). Views, nodes, the queue and plugins are
instance-level metadata and are not filtered: for a hard boundary also give the Jenkins user only the
permissions it needs (Overall/Read, Job/Read on the folders, Job/ExtendedRead only if `get_item_config`
is wanted).

## Tools (29 read-only, plus 3 opt-in tools when enabled)

| Group | Tools |
| --- | --- |
| Items | `get_item`, `get_item_config`, `get_item_parameters`, `get_all_items`, `query_items` |
| Builds | `list_builds`, `get_build`, `get_build_parameters`, `get_build_console_output`, `get_build_scripts`, `get_build_test_report`, `get_build_test_failures`, `get_running_builds`, `get_pending_inputs` |
| Artifacts | `get_all_build_artifacts`, `get_build_artifact`, `get_build_artifact_url` |
| Views / queue / nodes | `get_all_views`, `get_view`, `get_all_queue_items`, `get_queue_item`, `get_all_nodes`, `get_node` |
| Plugins | `get_all_plugins`, `get_plugin`, `get_plugins_with_problems`, `get_plugins_with_updates`, `get_plugins_with_backup`, `get_plugin_dependency_graph` |
| Trigger (opt-in) | `trigger_build(fullname, confirm=false)`, `stop_build(fullname, number, confirm=false)`, `cancel_queue_item(id, confirm=false)` |

`get_all_items` and an unfiltered `query_items` return very large results on a big instance: prefer
`query_items` with `fullname_pattern` and `folder_depth`.

## Maintaining this fork

```
uv sync
uv run pytest
uv run --with ruff ruff check src tests
```

Keep the fork read-only apart from the three allowlisted tools: a new tool must be a read tool, and nothing else that
sends a non-GET request to Jenkins is added without a separate, explicit decision. Upstream changes are taken by diff or
cherry-pick (the history is not shared). Release by tagging; the plugin pins a full commit SHA.

## License

MIT, as upstream: see [LICENSE](LICENSE). This is not an official Jenkins product.
