---
name: git-aliases
description: >-
  Documents the user's custom git aliases defined in ~/.gitconfig. Use when
  checking out a PR locally, creating a worktree from main, or removing a
  worktree. Covers: git pr, git mr, git wt, git wt-rm.
---

# Git Aliases

Custom aliases defined in `~/.gitconfig`. Prefer these over raw git commands.

## Checking out a PR locally

```bash
git pr <remote> <pr-number>
```

Fetches the PR head into a local branch `pr-<remote>-<pr-number>` and checks it out.

**Example** — check out PR 42 from `origin`:

```bash
git pr origin 42
# creates and checks out branch: pr-origin-42
```

Use this whenever the user asks to review or work on a PR locally instead of
manually running `git fetch` + `git checkout`.

## Checking out a GitLab MR locally

```bash
git mr <remote> <mr-number>
```

Same pattern as `git pr` but for GitLab merge requests. Creates branch
`mr-<remote>-<mr-number>`.

## Creating a worktree from latest main

```bash
git wt <name>
```

Runs `git fetch --all`, then creates a new worktree **and** a new branch named
`<name>` tracking `origin/main`. The worktree is placed at:

```
../<repo-name>-wt-<name>/
```

(sibling of the current repo root)

**Example** — start work on a feature in an isolated worktree:

```bash
git wt my-feature
# fetches all remotes, creates ../notegraph-wt-my-feature/ on branch my-feature
```

Use this when the user wants to work on something without disturbing the
current checkout, or when parallel work is needed.

## Removing a worktree

```bash
git wt-rm <name>
```

Removes the worktree at `../<repo-name>-wt-<name>/`. Run this after the
branch is merged and the worktree is no longer needed.

**Example:**

```bash
git wt-rm my-feature
# removes ../notegraph-wt-my-feature/
```

## Quick reference

| Alias      | What it does                                          |
|------------|-------------------------------------------------------|
| `git pr <remote> <N>`   | Fetch + checkout PR N from remote       |
| `git mr <remote> <N>`   | Fetch + checkout GitLab MR N from remote|
| `git wt <name>`         | New worktree + branch from origin/main  |
| `git wt-rm <name>`      | Remove worktree by name                 |
