---
name: sync-vikunja-waiting
description: >-
  One-way sync of Jira and GitHub work waiting on the user into Vikunja projects
  for prioritization. Invoked via ``notegraph todo --vikunja`` (upsert tasks,
  optional stale completion). Use when the user wants Vikunja updated from Jira/GitHub,
  mentions prioritizing assigned work, review queue, or syncing waiting items.
---

# Sync waiting work into Vikunja

## Goal

Refresh **Vikunja** from upstream **Jira** + **GitHub** so the user can triage in one place. Sync is **one-way** into Vikunja (upstream remains source of truth).

## What to run

Global flags (before ``todo``): **`-v` / `--verbose`** (debug logs), **`--dry-run`** (no Vikunja writes / no note files when combined with fetch or ``todo --sync``).

From the **notegraph** repo (this project), after exporting secrets:

```bash
cd /path/to/notegraph
uv run notegraph todo --vikunja
```

With explicit config:

```bash
uv run notegraph --config /path/to/config.toml todo --vikunja
```

Dry run (no Vikunja mutations):

```bash
uv run notegraph --dry-run todo --vikunja
```

By default, issues that **fall off** your waiting query get their Vikunja mirror **marked done**. To **leave those tasks open** instead:

```bash
uv run notegraph todo --vikunja --leave-vikunja-stale
```

Jira query uses the same **``--jql``** as ``notegraph todo`` (listing / ``--sync`` / ``--vikunja``), then ``JIRA_JQL`` env, ``[jira].jql``, then the built-in default.

```bash
uv run notegraph todo --vikunja --jql 'assignee = currentUser() AND status != Done ORDER BY updated DESC'
```

Update Logseq **and** Vikunja in one pass:

```bash
uv run notegraph todo --sync --vikunja
```

## Behaviour (short)

- **Jira:** JQL from ``--jql``, ``JIRA_JQL``, **`[jira].jql`**, then built-in default `assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC`.
- **GitHub:** Non-empty **`[vikunja].github_search_query`** → ``fetch_todo_search``; otherwise **`[github].orgs` / `repos`** → ``fetch_todo``. Needs ``github.token``. Scope is **not** narrowed by ``todo --source`` — Vikunja uses config only.
- **Vikunja:** **`[vikunja].token`** / `VIKUNJA_TOKEN`, **`[vikunja].base_url`** / `VIKUNJA_BASE_URL` (default `http://127.0.0.1:3456`). Project titles come from **`github_project_template`** / **`jira_project_template`** (defaults `{repo}`, `{project_key}`). Tasks carry a hidden `<!-- notegraph-sync id=github-org-repo-issue-N -->` (or `…-pull-…`, `jira-key`, etc.) marker — **do not remove** if you want stable upserts across runs.

## Agent workflow

1. Confirm **Vikunja** is reachable and `[vikunja].token` or `VIKUNJA_TOKEN` is set (do not commit secrets).
2. Run `uv run notegraph todo --vikunja` (add global `--dry-run` first if the user prefers a preview).
3. On errors, check logs for HTTP/auth failures; confirm `notegraph` config path with `--config` if needed.
4. After sync, the user can reorder/prioritize in Vikunja UI or via the **Vikunja MCP** tools.

## Reference

Environment variables, defaults, and edge cases: [reference.md](reference.md).
