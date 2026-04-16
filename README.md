# notegraph

Tools and scripts for working with Jira, GitHub issues, and notes in Logseq.

## Project layout

```
notegraph/
├── scripts/          # Shell scripts
│   └── gh-note.sh.in
├── cursor/           # Cursor rule templates (.mdc.in)
│   ├── cursortodo.mdc.in
│   ├── gh-notes.mdc.in
│   ├── jira-notes.mdc.in
│   ├── journal.mdc.in
│   └── todo.mdc.in
├── build/            # Generated files (gitignored)
│   └── cursor/       # Built .mdc rules
├── .cursor/rules/    # Workspace copy of built rules (gitignored)
└── Makefile
```

Cursor rules are generated from `.mdc.in` templates via `make`. The build substitutes:

| Variable | Purpose | Example value |
|----------|---------|---------------|
| `{{JIRA_ENDPOINT}}` | Jira hostname for URLs and wikilinks | `redhat.atlassian.net` |

## Quick start

```bash
make install JIRA_ENDPOINT=yourorg.atlassian.net
```

This builds everything into `build/`, then installs to:

| What | Default destination | Override |
|------|---------------------|----------|
| Cursor rules (global) | `~/.cursor/rules` | `RULESDIR` |
| Cursor rules (workspace) | `.cursor/rules/` | — |

Other make targets:

| Target | Effect |
|--------|--------|
| `make` (or `make all`) | Build into `build/` only |
| `make install` | Build + copy to destinations |
| `make cursor` | Build Cursor rules only |
| `make test` | Run Python tests |
| `make clean` | Remove `build/` and workspace rules |

## Cursor rules

All rules are `alwaysApply: true` and are loaded by Cursor for every session.

| Rule | Purpose |
|------|---------|
| `gh-notes` | Auto-create and use GitHub issue/PR note files |
| `jira-notes` | Auto-create and use Jira issue note files |
| `todo` | Workflow for worktodo.md Focus/Backlog/Incoming |
| `journal` | Keep today's Logseq journal page updated via MCP |
| `cursortodo` | Track actionable improvements discovered during sessions via MCP |

## Logseq Note Scripts

### gh-note.sh

Creates Logseq pages from GitHub issues and PRs.

```bash
gh-note.sh [--check] [--md-only] [-d <dir>] <github-url>
```

| Flag | Effect |
|------|--------|
| (none) | Fetch from GitHub and create missing files |
| `--check` | Print JSON with file paths and existence, no network calls |
| `--md-only` | Only create the .md file (skip note and cursor) |
| `-d <dir>` | Override target directory (default: `~/Documents/Logseq/Work/pages`) |
