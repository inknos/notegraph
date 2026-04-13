# notegraph

Tools and scripts for working with Jira, GitHub issues, and notes in Logseq.

## Project layout

```
notegraph/
├── scripts/          # Script templates (.sh.in)
│   ├── gh-note.sh.in
│   ├── jira-note.sh.in
│   └── todo-page.sh.in
├── cursor/           # Cursor rule templates (.mdc.in)
│   ├── cursortodo.mdc.in
│   ├── gh-notes.mdc.in
│   ├── jira-notes.mdc.in
│   ├── journal.mdc.in
│   └── todo.mdc.in
├── build/            # Generated files (gitignored)
│   ├── scripts/      # Built .sh scripts
│   └── cursor/       # Built .mdc rules
├── .cursor/rules/    # Workspace copy of built rules (gitignored)
├── jira/             # go-jira clone with config
└── Makefile
```

All scripts and rules are generated from `.in` templates via `make`. The build substitutes:

| Variable | Purpose | Example value |
|----------|---------|---------------|
| `{{JIRA_ENDPOINT}}` | Jira hostname for URLs and wikilinks | `redhat.atlassian.net` |
| `{{SCRIPT_DIR}}` | Absolute path to scripts directory | `/home/user/notegraph/scripts` |

## Quick start

```bash
make install JIRA_ENDPOINT=yourorg.atlassian.net
```

This builds everything into `build/`, then installs to:

| What | Default destination | Override |
|------|---------------------|----------|
| Scripts | `~/.local/bin` | `BINDIR` |
| Cursor rules (global) | `~/.cursor/rules` | `RULESDIR` |
| Cursor rules (workspace) | `.cursor/rules/` | — |

Other make targets:

| Target | Effect |
|--------|--------|
| `make` (or `make all`) | Build into `build/` only |
| `make install` | Build + copy to destinations |
| `make scripts` | Build scripts only |
| `make cursor` | Build Cursor rules only |
| `make test` | Run bats tests |
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

## go-jira CLI Setup

[go-jira](https://github.com/go-jira/jira) is a command-line Jira client written in Go. The upstream binary doesn't ship with GNOME keyring support, so we build from source with the `gnome_keyring` tag.

### Prerequisites

- Go toolchain
- `libsecret-1` dev headers (`libsecret-1-dev` on Debian/Ubuntu, `libsecret-devel` on Fedora)
- `secret-tool` (usually part of `libsecret-tools` / `libsecret`)
- A Jira Personal Access Token (PAT)

### Clone and build

```bash
git clone git@github.com:go-jira/jira.git && cd jira
make build
```

### Configure

Edit `.jira.d/config.yml` inside the repo:

```yaml
authentication-method: api-token   # see "Auth methods" below
password-source: keyring
user: YOURLOGIN
login: YOURLOGIN@email.com
endpoint: https://DOMAIN.atlassian.net
project: RUN
```

### Auth methods

The correct `authentication-method` depends on which Jira instance you target:

| Instance | Method | HTTP header |
|---|---|---|
| Atlassian Cloud (`domain.atlassian.net`) | `api-token` | `Authorization: Basic base64(login:token)` |
| On-premise / SSO (`issues.domain.com`) | `bearer-token` | `Authorization: Bearer <token>` |

Using the wrong method will result in `403 Forbidden`.

### Store the token in GNOME keyring

Get a PAT from **Jira Web UI -> Profile -> Personal Access Tokens**, then store it:

```bash
secret-tool store --label='go-jira' \
  username 'api-token:YOURLOGIN@email.com' \
  service go-jira \
  xdg:schema org.github.tmc.keyring.Password
```

It will prompt for the secret — paste your PAT.

The `xdg:schema` attribute is required. The Go keyring library (`tmc/keyring`) uses a custom libsecret schema (`org.github.tmc.keyring.Password`); without it, `secret-tool` stores under the generic schema and the Go library won't find it.

### Run from source

```bash
go run -tags gnome_keyring cmd/jira/main.go view RUN-1234
```

The `-tags gnome_keyring` flag is required to compile with libsecret support instead of the D-Bus fallback.

### Shell shortcut

Add to `~/.bashrc` so you can use `jira` from anywhere:

```bash
jira() {
  pushd "$HOME/Documents/personal_projects/notegraph/jira" > /dev/null
  go run -tags gnome_keyring cmd/jira/main.go "$@"
  popd > /dev/null
}
```

The `pushd` is needed because go-jira reads `.jira.d/config.yml` relative to the working directory.

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

### jira-note.sh

Creates Logseq pages from Jira issues. For Epics it crawls all child issues and chains into `gh-note.sh` for linked GitHub PRs.

```bash
jira-note.sh [--check] [-d <dir>] <ISSUE-KEY>
```

| Flag | Effect |
|------|--------|
| (none) | Fetch from Jira and create/update files |
| `--check` | Print JSON with file paths and existence, no network calls |
| `-d <dir>` | Override target directory (default: `~/Documents/Logseq/Work/pages`) |

The `JIRA_REPO` env var can override the go-jira repo path (default: `~/Documents/personal_projects/notegraph/jira`).

**What gets created:**

| Item | md | note | cursor |
|---|---|---|---|
| Epic (if any child is open) | yes (always refreshed) | no | no |
| Child (open) | yes (always refreshed) | yes (write-once) | yes (write-once) |
| Child (closed) | yes (always refreshed) | no | no |
| Linked GitHub PR (open child) | yes (via gh-note.sh) | yes | yes |
| Linked GitHub PR (closed child) | yes (via gh-note.sh --md-only) | no | no |

Re-running the script on the same epic picks up new children and refreshes md files without overwriting note/cursor files.

### todo-page.sh

Generates a `todo.md` dashboard in Logseq by crawling GitHub and Jira for your active items.

```bash
todo-page.sh [--sync] [--org <org>]... [--repo <owner/repo>]...
```

| Flag | Effect |
|------|--------|
| `--org <org>` | Search all repos in a GitHub org (repeatable) |
| `--repo <owner/repo>` | Search a specific GitHub repo (repeatable) |
| `--sync` | Also create/refresh individual note pages via `gh-note.sh` / `jira-note.sh` |

At least one `--org` or `--repo` is required. Both can be combined.

**GitHub** — searches for open issues/PRs where you're involved (assigned, authored, mentioned, commented) or where your review is requested. Your GitHub username is resolved via `gh api user`.

**Jira** — queries issues assigned to `currentUser()` that are not Closed.

**Output** — a single `todo.md` page grouped by source (GitHub / Jira) and by repo/project, with Logseq wikilinks to individual note pages.

**Examples:**

```bash
# Just build the todo page
todo-page.sh --org containers

# Multiple scopes
todo-page.sh --org containers --repo inknos/some-tool

# Build the todo page and sync individual note pages
todo-page.sh --org containers --sync
```

**Cron setup** (every 30 minutes):

```
*/30 * * * * ~/.local/bin/todo-page.sh --org containers --sync
```

### Troubleshooting

**`403 Forbidden`** — Wrong `authentication-method` for the Jira instance, or expired/invalid token. See the auth methods table above.

**`Gnome-keyring error: <nil>` + panic** — The token isn't stored with the correct schema. Re-run the `secret-tool store` command with `xdg:schema org.github.tmc.keyring.Password`.

**`JIRA_API_TOKEN` env var** — As a quick workaround you can skip the keyring entirely. Comment out `password-source: keyring` in config and run:

```bash
JIRA_API_TOKEN='your-token' go run -tags gnome_keyring cmd/jira/main.go view RUN-1234
```
