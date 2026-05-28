# No GitHub Writes

**Never** perform any write operation on GitHub. This includes:

- Posting or editing PR/issue comments
- Submitting or editing reviews
- Creating or updating PRs or issues
- Pushing branches to remote
- Merging, closing, or reopening PRs/issues
- Reacting to comments
- Any `gh` CLI command that modifies state (e.g. `gh pr comment`, `gh pr review`, `gh issue comment`, `gh pr create`, `git push`)

Read-only operations (viewing PRs, fetching issue data, reading comments) are fine.

If a task would require writing to GitHub, stop and tell the user what you would do, so they can do it themselves.

---

# Work Journal

The agent maintains a running log of its activity on today's Logseq journal page, using the `user-mcp-logseq` MCP server.

## Discovering today's page

Logseq journal pages are named by date. The default title format is `MMM do, yyyy` (e.g. `Apr 9th, 2026`). To find today's page:

1. Call `get_page_content` with today's date formatted as the page name (e.g. `Apr 9th, 2026`).
2. If the page doesn't exist, call `create_page` with that title.

Do NOT hardcode file paths. Always go through the MCP.

## When to write

**After every response that changes files or state.** At the end of any turn where you edited files, ran commands, posted comments, updated notes, or performed any non-trivial action, update the journal. Skip trivial turns that only answer a question or provide information without changing anything.

This means:

- On the first substantive turn, read the journal page (`get_page_content` with `format: "json"` to get block UUIDs) and append a breadcrumb bullet.
- On subsequent turns, refactor your earlier `Agent session:` bullets from this session to accurately reflect the current state of work. Use `update_block` with the block UUID to edit in place. Consolidate multiple small steps into a single clear bullet when appropriate.
- Never edit or remove blocks written by the user or by previous sessions.

## End-of-turn checklist

Before finishing every response, verify:

1. Did I change files, run commands that modify state, or update notes this turn?
2. If yes, did I update today's journal page?

If the answer to (1) is yes and (2) is no, update the journal NOW before ending your turn. This check is mandatory and must not be skipped.

## How to read and write

| Action | MCP tool | Notes |
|--------|----------|-------|
| Read journal | `get_page_content` with `format: "json"` | Returns blocks with UUIDs so you can edit them later |
| Append new entry | `update_page` with `mode: "append"` | Adds blocks after existing content |
| Edit your own entry | `update_block` with the block's UUID | Only for `Agent session:` blocks you wrote this session |
| Create journal page | `create_page` with today's date as title | Only if the page doesn't exist yet |

## Entry format

Each entry is a top-level block prefixed with `Agent session:` so the user can distinguish agent-written entries from their own.

```markdown
- Agent session: reviewed PR [[github.com/org/repo/pull/123]] — approved with minor comments
- Agent session: updated notegraph rules — renamed cursor references to agent
- Agent session: investigated flaky test in [[redhat.atlassian.net/RUN-1234]], root cause is race condition in setup
```

## What to log

Log any action that changes files or state:

- PR/issue reviews, comments, approvals
- Code changes, refactors, bug fixes
- Config or rule file edits
- Script or build system changes
- Note page updates (agent files, worktodo, etc.)
- Triage or planning activity
- Debugging or investigation with findings

Do NOT log: answering informational questions, reading files without acting on them, or trivial clarifications.

## Rules

1. **Always link.** Every mention of a GitHub issue, PR, or Jira card must be a `[[wikilink]]` (e.g. `[[github.com/org/repo/pull/123]]`, `[[redhat.atlassian.net/KEY-123]]`). Link to agent notes as `[[.../agent]]` when relevant.
2. **Be brief.** One line per activity. State *what* happened and the outcome or next step.
3. **Refactor your own entries, never touch others.** You may edit or consolidate `Agent session:` blocks you wrote in this session to keep the journal clean and accurate. Never edit or remove blocks written by the user or by previous sessions.
4. **Derive from context.** Build the entry from what you actually did. Don't ask the user to dictate it.
5. **Read before writing.** Always read the journal page first (with `format: "json"`) to get block UUIDs and avoid duplicates.
6. **No bare hashtags.** Never use `#word` in Logseq content — Logseq interprets `#foo` as a page reference (equivalent to `[[foo]]`). If you need a literal hash (e.g. issue numbers), escape it or rephrase.

---

# Worktodo Workflow

The user maintains a work todo file at `~/Documents/Logseq/Work/pages/worktodo.md` with three sections:

| Section | Meaning |
|---------|---------|
| **Focus** | Actively working on — pick from here first |
| **Backlog** | Queued items — promote to Focus when ready |
| **Incoming** | New items from sync — needs triage |

Items are Logseq wikilinks: `- [[github.com/org/repo/pull/123]] title (**status**)` or `- [[redhat.atlassian.net/KEY-123]] KEY-123 title (**status**)`.

## When the user asks to work on their todo

1. **Read** `~/Documents/Logseq/Work/pages/worktodo.md`.
2. **Show Focus items** and ask which one to work on (or suggest the most stale / most urgent).
3. **Get context** on the chosen item:
   - GitHub URL → run `notegraph fetch --source github --check --json <url>`, then read the `.md` and `-note.md` files. Create missing files if needed (run `notegraph fetch --source github <url>`).
   - Jira key → run `notegraph fetch --source jira --check --json <KEY>`, then read the `.md` and `-note.md` files. Create missing files if needed (run `notegraph fetch --source jira <KEY>`).
4. **Write analysis** to the `-agent.md` file (see the GitHub Issue/PR Notes section for the full protocol).
5. **Proceed** with the work — code changes, PR comments, review, etc.

## Triaging Incoming

When the user asks to triage:

1. Read the Incoming section.
2. For each item, briefly summarize it (fetch context if needed).
3. Ask the user whether to move it to **Focus**, **Backlog**, or leave it in Incoming.
4. Edit `worktodo.md` to move the wikilink line to the chosen section. Preserve the existing order within each section.

## Refreshing the list

To sync with GitHub/Jira, run:

```
notegraph todo --sync [--org <org>] [--repo <owner/repo>]
```

The `--sync` flag writes `worktodo.md` and fetches note triplets for each item. The user's Focus/Backlog ordering is preserved; new items land in Incoming.

---

# GitHub Issue/PR Notes

When the user references a GitHub issue or PR URL, **always** look up or create structured note files **before doing anything else**. Do not proceed with review, code changes, analysis, or any other work until step 5 (writing the agent file) is complete. This workflow is mandatory, not optional.

## Trigger

Any GitHub URL matching `https://github.com/{org}/{repo}/{issues|pull}/{number}`.

## Workflow

1. **Locate files.** Run `notegraph fetch --source github --check --json <url>` to get a JSON object with the paths and existence status of all three files (`md`, `note`, `agent`).

2. **Create if missing.** If any file has `"exists": false`, run `notegraph fetch --source github <url>` to fetch from GitHub and create the missing files.

3. **Read the summary.** Read the `md` file (`N.md`). It contains the title, description, raw comments, and a Key Discussion Points section. Use this as your primary context about the issue/PR.

4. **Read the user's notes (read-only).** Read the `note` file (`N-note.md`). These are the user's personal notes, TODOs, and related links. **Never modify this file** -- it belongs to the user.

5. **Write your analysis to the agent file.** The `agent` file is your workspace. Write a markdown file containing your analysis:
   - Summary of the issue/PR and key discussion points
   - Actionable TODOs and next steps
   - Technical notes, code pointers, and suggestions
   - Anything useful for the user to act on

   Keep the file concise and actionable. Update it every time you work on this issue/PR.

## CLI reference

`notegraph fetch --source github [OPTIONS] <github-url>`

| Flag | Effect |
|------|--------|
| (none) | Fetch from GitHub and create missing files |
| `--check` | Show file paths and existence (table format) |
| `--check --json` | Show file paths and existence (JSON format) |
| `--replace` | Overwrite existing note/agent files |
| `--summary` | Only create the summary (md) file |
| `--note` | Only create the user-notes file |
| `--analysis` | Only create the agent-analysis file |
| `--dest-dir DIR` | Override output directory |

The `--check --json` output looks like:

```json
{
  "md":     { "path": "/path/to/N.md",          "exists": true  },
  "note":   { "path": "/path/to/N-note.md",     "exists": true  },
  "agent":  { "path": "/path/to/N-agent.md",    "exists": false }
}
```

## File purposes

| File | Owner | Purpose |
|------|-------|---------|
| `N.md` | Tool | Auto-populated summary, description, and raw comments from GitHub |
| `N-note.md` | User | User's personal working notes -- **read-only for the agent** |
| `N-agent.md` | Agent | Agent's analysis, TODOs, and notes -- **agent writes here** |

---

# Jira Issue Notes

When the user references a Jira issue, look up or create structured note files, then use them.

## Trigger

Any Jira URL matching `https://redhat.atlassian.net/browse/<KEY>`, or a bare Jira key like `RUN-3555`.

## Workflow

1. **Locate files.** Run `notegraph fetch --source jira --check --json <KEY>` to get a JSON object with the paths and existence status of the md, note, and agent files.

2. **Create if missing.** If any file has `"exists": false`, run `notegraph fetch --source jira <KEY>` to fetch from Jira and create the files. If the issue has a linked GitHub PR (via a Jira custom field), the linked PR's note files are also created automatically.

3. **Read the summary.** Read the `md` file. It contains the title, description, status, and comments.

4. **Read the user's notes (read-only).** Read the `note` file if it exists. These are the user's personal notes, TODOs, and related links. **Never modify this file** -- it belongs to the user.

5. **Write your analysis to the agent file.** The `agent` file is your workspace. Write a markdown file containing your analysis:
   - Summary of the issue and key discussion points
   - Actionable TODOs and next steps
   - Technical notes, code pointers, and suggestions
   - Anything useful for the user to act on

   Keep the file concise and actionable. Update it every time you work on this issue.

## CLI reference

`notegraph fetch --source jira [OPTIONS] <ISSUE-KEY>`

| Flag | Effect |
|------|--------|
| (none) | Fetch from Jira and create missing files |
| `--check` | Show file paths and existence (table format) |
| `--check --json` | Show file paths and existence (JSON format) |
| `--replace` | Overwrite existing note/agent files |
| `--summary` | Only create the summary (md) file |
| `--note` | Only create the user-notes file |
| `--analysis` | Only create the agent-analysis file |
| `--dest-dir DIR` | Override output directory |

The `--check --json` output looks like:

```json
{
  "md":     { "path": "/path/to/KEY.md",          "exists": true  },
  "note":   { "path": "/path/to/KEY-note.md",     "exists": true  },
  "agent":  { "path": "/path/to/KEY-agent.md",    "exists": false }
}
```

## File purposes

| File | Owner | Purpose |
|------|-------|---------|
| `KEY.md` | Tool | Auto-populated summary, description, and comments |
| `KEY___note.md` | User | User's personal working notes -- **read-only for the agent** |
| `KEY___agent.md` | Agent | Agent's analysis, TODOs, and notes -- **agent writes here** |

---

# Agent TODO Tracker

The agent maintains a running list of actionable improvements, bugs, and follow-ups on the `agenttodo` Logseq page, using the `user-mcp-logseq` MCP server.

## How to read and write

| Action | MCP tool | Notes |
|--------|----------|-------|
| Read the page | `get_page_content` with `page_name: "agenttodo"`, `format: "json"` | Returns blocks with UUIDs for editing |
| Append new items | `update_page` with `page_name: "agenttodo"`, `mode: "append"` | Adds blocks after existing content |
| Mark item done | `update_block` with the block's UUID | Wrap text in `~~strikethrough~~` and append `(done YYYY-MM-DD)` |
| Create page | `create_page` with `title: "agenttodo"` | Only if the page doesn't exist yet |

Do NOT hardcode file paths. Always go through the MCP.

## When to write

1. **After a review or investigation.** If you found bugs, improvement ideas, or follow-up actions in a PR/issue, add them here.
2. **After completing a TODO.** Mark it done with `~~strikethrough~~` via `update_block` — don't delete it.
3. **Before starting work.** Read `agenttodo` to check for outstanding items related to the current repo or PR.

## Entry format

Items are grouped under a repo heading. Each item links to the PR/issue and the agent notes file.

```markdown
- **org/repo**
  - [[github.com/org/repo/pull/123]] brief description of improvement — details in [[github.com/org/repo/pull/123/agent]]
  - ~~[[github.com/org/repo/issue/456]] fixed: description~~ (done 2026-04-09)
```

## Rules

1. **Always link.** Every item must include a `[[wikilink]]` to the PR/issue and optionally to the agent notes file.
2. **Group by repo.** Use `- **org/repo**` as a top-level block. Add items as children (use `insert_nested_block` with the repo block's UUID). If the repo heading already exists, add under it.
3. **Be specific.** State what needs to happen, not just what was observed. "Refactor X to handle Y" is better than "X has a problem".
4. **Mark done, don't delete.** Use `update_block` to wrap completed items in `~~strikethrough~~` and append `(done YYYY-MM-DD)`.
5. **Read before writing.** Always read the page first (with `format: "json"`) to get block UUIDs and avoid duplicates.
6. **No bare hashtags.** Never use `#word` in Logseq content — Logseq interprets `#foo` as a page reference (equivalent to `[[foo]]`). If you need a literal hash (e.g. issue numbers), escape it or rephrase.
