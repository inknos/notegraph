# sync-vikunja-waiting — reference

## Notes vs Vikunja

- **`todo --sync`** writes ``worktodo.md`` and fetches/writes Logseq **md / note / cursor** triplets from GitHub and Jira APIs.
- **`todo --vikunja`** mirrors waiting items into Vikunja. **Task titles** are stable ids only (Jira issue key, GitHub sync slug like ``github-org-repo-issue-N``); the human summary is in the task description. It does **not** read or embed Logseq notes.

## Environment variables

Config file: ``~/.config/notegraph/config.toml`` (or ``--config``). Use section ``[vikunja]`` for ``base_url``, ``token``, optional ``github_search_query``, and optional ``github_project_template`` / ``jira_project_template`` (``str.format``; defaults ``{repo}`` and ``{project_key}``). Same keys can be overridden by env:

| Variable | Overrides `[vikunja]` key |
|----------|---------------------------|
| `VIKUNJA_TOKEN` | `token` |
| `VIKUNJA_BASE_URL` | `base_url` |

Jira sync uses `[jira]` / `JIRA_*` as elsewhere; **JQL** resolution order is **`--jql`**, then `JIRA_JQL`, then **`[jira].jql`** from the config file, then the built-in default.

## GitHub scope

- If **`[vikunja].github_search_query`** is non-empty: uses ``notegraph.github.fetch_todo_search`` (single global ``q``).
- If it is **empty**: uses ``notegraph.github.fetch_todo`` with **`[github].orgs`** and **`[github].repos`** — same involvement + review-requested queries as ``notegraph todo``.

Default when both are unset: GitHub is skipped (warning logged).

## Indexed 0 Vikunja tasks

The INFO line counts tasks returned from Vikunja's task-list API **before** this run creates or updates anything. **Zero is normal** when the server truly has no tasks (e.g. empty namespace). Some Vikunja versions return an empty ``GET /tasks`` even when project tasks exist — notegraph then retries ``GET /tasks/all``. If the UI shows tasks but the count stays **0**, note your Vikunja version and report it.

## Troubleshooting Vikunja HTTP 401

If Jira/GitHub succeed but Vikunja returns **401 Unauthorized**:

- Ensure **`[vikunja].token`** is set in your config **or** **`VIKUNJA_TOKEN`** is exported. A plain `~/.config/notegraph/config.toml` without a `[vikunja]` section has **no** Vikunja token unless the env var is set.
- Create a new **API token** in Vikunja (user settings → API tokens). Paste **only** the token string, not the word `Bearer` (a duplicated `Bearer` prefix is stripped automatically).
- Confirm **`[vikunja].base_url`** matches the Vikunja instance you log into (default `http://127.0.0.1:3456`).
- Re-run with **`-v`** for DEBUG lines from ``notegraph.*`` (per-task upsert decisions). Raw urllib3 request dumps stay suppressed.

## Vikunja layout

- **Task titles:** Jira issue key (e.g. ``RUN-3555``) or GitHub slug (``github-org-repo-issue-42`` / ``…-pull-42``). Human summaries live in the **description**, so upstream summary edits do not change the Vikunja title.
- All tasks land in **two projects**: **JIRA** and **GitHub** (defaults for `[vikunja].jira_project_template` and `github_project_template`). Override with `str.format` templates if you want per-repo/per-key projects (e.g. `"{repo}"`, `"{project_key}"`).
- Tasks get **`start_date`** only when assigned to you: GitHub **pull requests** use PR creation day (you authored them); GitHub **issues** use the latest timeline **assignment** to you; Jira uses the latest changelog transition assigning you. Issues/cards **not** assigned to you get **no** `start_date`. Extra REST calls: one per GitHub issue and one per Jira issue.
- Tasks with a `start_date` get **weekly reminders** — absolute timestamps at `start_date + 7d`, `+14d`, `+21d`, … up to "now". The full list is regenerated on every sync run. Tasks without a `start_date` get no reminders.
- **Jira priority** is mapped to Vikunja integers: Blocker/Highest → 4 (urgent), Critical/High → 3 (high), Major/Medium → 2 (medium), Minor/Low → 1 (low), Trivial/unknown → 0 (unset). GitHub items always get priority 0.
- Only tasks **with** the `notegraph-sync` marker whose sync id looks like ``jira-…`` / ``github-…`` (legacy ``jira:…`` / ``github:…`` is normalized) are eligible for **automatic completion** when they disappear from Jira/GitHub — unless ``todo --vikunja`` is run with **`--leave-vikunja-stale`**, which keeps those mirrors open. Project renaming does not affect this behaviour.
- Manual tasks without the marker are untouched.

## Implementation

Python module: `notegraph.vikunja_sync`, invoked from CLI as ``notegraph todo --vikunja``.
