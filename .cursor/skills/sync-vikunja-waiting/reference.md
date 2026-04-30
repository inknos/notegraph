# sync-vikunja-waiting — reference

## Environment variables

Config file: ``~/.config/notegraph/config.toml`` (or ``--config``). Use section ``[vikunja]`` for ``base_url``, ``token``, optional ``github_search_query``, and optional ``github_project_template`` / ``jira_project_template`` (``str.format``; defaults ``{repo}`` and ``{project_key}``). Same keys can be overridden by env:

| Variable | Overrides `[vikunja]` key |
|----------|---------------------------|
| `VIKUNJA_TOKEN` | `token` |
| `VIKUNJA_BASE_URL` | `base_url` |

Jira sync uses `[jira]` / `JIRA_*` as elsewhere; **JQL** resolution order is `--jira-jql`, then `JIRA_JQL`, then **`[jira].jql`** from the config file, then the built-in default.

## GitHub scope

- If **`[vikunja].github_search_query`** is non-empty: uses ``notegraph.github.fetch_todo_search`` (single global ``q``).
- If it is **empty**: uses ``notegraph.github.fetch_todo`` with **`[github].orgs`** and **`[github].repos`** — same involvement + review-requested queries as ``notegraph todo``.

Default when both are unset: GitHub is skipped (warning logged).

## Troubleshooting Vikunja HTTP 401

If Jira/GitHub succeed but Vikunja returns **401 Unauthorized**:

- Ensure **`[vikunja].token`** is set in your config **or** **`VIKUNJA_TOKEN`** is exported. A plain `~/.config/notegraph/config.toml` without a `[vikunja]` section has **no** Vikunja token unless the env var is set.
- Create a new **API token** in Vikunja (user settings → API tokens). Paste **only** the token string, not the word `Bearer` (a duplicated `Bearer` prefix is stripped automatically).
- Confirm **`[vikunja].base_url`** matches the Vikunja instance you log into (default `http://127.0.0.1:3456`).
- Re-run with **`-v`** for urllib3 DEBUG lines (request URL and status).

## Vikunja layout

- Projects are created as needed using **`[vikunja].github_project_template`** and **`[vikunja].jira_project_template`** (defaults: `{repo}`, `{project_key}` — e.g. `containers/podman`, `RUN`).
- Tasks get **`start_date`** when syncing: GitHub **pull requests** use PR creation day; GitHub **issues** use the latest timeline **assignment** to you (falls back to creation day); Jira uses the latest changelog transition assigning the **current** assignee (falls back to creation day). Extra REST calls: one per GitHub issue and one per Jira issue.
- Only tasks **with** the `notegraph-sync` marker whose sync id looks like ``jira-…`` / ``github-…`` (legacy ``jira:…`` / ``github:…`` is normalized) are eligible for **automatic completion** when they disappear from Jira/GitHub — unless ``todo --vikunja`` is run with **`--leave-vikunja-stale`**, which keeps those mirrors open. Project renaming does not affect this behaviour.
- Manual tasks without the marker are untouched.

## Implementation

Python module: `notegraph.vikunja_sync`, invoked from CLI as ``notegraph todo --vikunja``.
