"""Notegraph CLI — cyclopts-based command-line interface.

Usage::

    notegraph [--config PATH] github [OPTIONS] [URL]
    notegraph [--config PATH] jira   [OPTIONS] KEY

Global options (before the subcommand):

    --config PATH         Path to TOML config file
                          (default: ~/.config/notegraph/config.toml).

Subcommand options (github / jira):

    --check               Show file paths and existence, then exit.
    --json                Output JSON instead of human-readable text.
                          With --check: JSON triplet.  Without --check:
                          rendered file contents (no files written).
    --summary             Include the summary (md) file.
    --note                Include the user-notes file.
    --analysis            Include the agent-analysis (cursor) file.
    --no-summary          Exclude the summary file.
    --no-note             Exclude the user-notes file.
    --no-analysis         Exclude the agent-analysis file.
    --replace             Overwrite existing note/analysis files.
    --dest-dir DIR        Override output directory.

GitHub todo options (use instead of URL):

    --todo                List open issues/PRs you are involved in.
    --org ORG             GitHub org to search (repeatable).
    --repo OWNER/REPO     GitHub repo to search (repeatable).

Jira todo options (use instead of KEY):

    --todo                List issues matching a JQL query.
    --jql QUERY           JQL query (overrides config; empty = no search).

File selection logic:

    If any *positive* flag (--summary, --note, --analysis) is given,
    only those kinds are included.  If none are given the default is
    all three.  Negative flags (--no-summary, etc.) subtract from
    whatever set is active.

Examples::

    notegraph github --check https://github.com/org/repo/pull/1
    notegraph github --check --json https://github.com/org/repo/pull/1
    notegraph github --summary https://github.com/org/repo/pull/1
    notegraph github --todo --org containers
    notegraph github --todo --org containers --repo myorg/tool --json
    notegraph jira --analysis --note RUN-3555
    notegraph jira --todo
    notegraph jira --todo --jql "assignee = currentUser() AND status != Done"
    notegraph jira --todo --json
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Annotated, Any

from cyclopts import App, Group, Parameter
from pydantic import BaseModel

from notegraph import github as github_api
from notegraph import jira as jira_api
from notegraph import writer
from notegraph.github import FetchError as GitHubFetchError
from notegraph.jira import FetchError as JiraFetchError
from notegraph.schema import (
    FileKind,
    GitHubRef,
    JiraRef,
    NoteContent,
)
from notegraph.writer import check as writer_check

DEFAULT_CONFIG_PATH = Path("~/.config/notegraph/config.toml").expanduser()

app = App(name="notegraph", help="Note graph generator for GitHub and Jira issues.")
app.meta.group_parameters = Group("Global Options", sort_key=0)

# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class JiraConfig(BaseModel):
    """Jira-specific configuration."""

    endpoint: str = ""
    email: str = ""
    token: str = ""
    repo: str = "~/Documents/personal_projects/notegraph/jira"
    github_field: str = "customfield_10875"
    jql: str = ""


class GitHubConfig(BaseModel):
    """GitHub-specific configuration."""

    token: str = ""


class LogseqConfig(BaseModel):
    """Logseq output configuration."""

    graph_dir: str = "~/Documents/Logseq/Work/pages"


class AppConfig(BaseModel):
    """Full application config, assembled from TOML + env vars.

    Not directly a CLI parameter — built inside command handlers from
    the ``--config`` path.
    """

    jira: JiraConfig = JiraConfig()
    github: GitHubConfig = GitHubConfig()
    logseq: LogseqConfig = LogseqConfig()

    @property
    def dest_dir(self) -> str:
        """Resolve output directory from the Logseq config."""
        return str(Path(self.logseq.graph_dir).expanduser())


def load_config(config_path: Path) -> AppConfig:
    """Load config from a TOML file, with env-var overrides.

    Args:
        config_path: Path to the TOML config file.

    Returns:
        Assembled ``AppConfig``.
    """
    data: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("rb") as f:
            data = tomllib.load(f)

    _apply_env_overrides(data)

    return AppConfig.model_validate(data)


def _apply_env_overrides(data: dict[str, Any]) -> None:
    """Merge environment variables into the config dict (in-place).

    Args:
        data: Mutable config dictionary to update.
    """
    jira = data.setdefault("jira", {})
    github = data.setdefault("github", {})

    if token := os.environ.get("JIRA_TOKEN"):
        jira["token"] = token
    if email := os.environ.get("JIRA_EMAIL"):
        jira["email"] = email
    if endpoint := os.environ.get("JIRA_ENDPOINT"):
        jira["endpoint"] = endpoint
    if token := os.environ.get("GITHUB_TOKEN"):
        github["token"] = token


# ---------------------------------------------------------------------------
# Global state — populated by the meta launcher, read by subcommands
# ---------------------------------------------------------------------------

_cfg: AppConfig | None = None


def _get_config() -> AppConfig:
    """Return the loaded config, falling back to defaults if meta was bypassed.

    Returns:
        The active ``AppConfig``.
    """
    global _cfg  # noqa: PLW0603
    if _cfg is None:
        _cfg = load_config(DEFAULT_CONFIG_PATH)
    return _cfg


# ---------------------------------------------------------------------------
# Meta launcher — parses global options before subcommand dispatch
# ---------------------------------------------------------------------------


@app.meta.default
def launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    config: Annotated[
        Path,
        Parameter(help="Path to config file."),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """Launch notegraph with global options."""
    global _cfg  # noqa: PLW0603
    _cfg = load_config(config)
    app(tokens)


# ---------------------------------------------------------------------------
# File-kind selection helpers
# ---------------------------------------------------------------------------

_KIND_MAP: dict[str, FileKind] = {
    "summary": "md",
    "note": "note",
    "analysis": "cursor",
}


def _resolve_kinds(
    *,
    summary: bool,
    note: bool,
    analysis: bool,
) -> tuple[FileKind, ...]:
    """Resolve the ``--summary / --note / --analysis`` flags into file kinds.

    If any positive flag is set, start with only those kinds.
    If none are set, start with all three.
    Negative flags (``--no-*``) are handled by cyclopts toggling the
    bool to ``False``, but since ``False`` is also the default we
    distinguish "explicitly negated" from "not mentioned" by checking
    whether *any* positive flag was given.

    The convention is:
    - All ``False`` (default) -> all kinds.
    - At least one ``True``   -> only the ``True`` ones.

    Args:
        summary: Include the summary (md) file.
        note: Include the user-notes file.
        analysis: Include the agent-analysis (cursor) file.

    Returns:
        Tuple of ``FileKind`` values to process.

    Raises:
        SystemExit: If the resolved set is empty.
    """
    flags = {"summary": summary, "note": note, "analysis": analysis}
    any_positive = any(flags.values())

    if any_positive:
        selected = [_KIND_MAP[name] for name, on in flags.items() if on]
    else:
        selected = list(_KIND_MAP.values())

    if not selected:
        sys.stderr.write("Error: no file kinds selected.\n")
        raise SystemExit(1)

    return tuple(selected)


# ---------------------------------------------------------------------------
# Subcommand parameter models
# ---------------------------------------------------------------------------


class GitHubArgs(BaseModel):
    """Arguments for the ``github`` subcommand."""

    url: Annotated[
        str | None,
        Parameter(help="GitHub issue or PR URL (required unless --todo)."),
    ] = None
    todo: Annotated[
        bool,
        Parameter(help="List open issues/PRs you are involved in."),
    ] = False
    org: Annotated[
        list[str],
        Parameter(help="GitHub org to search (repeatable, for --todo)."),
    ] = []
    repo_filter: Annotated[
        list[str],
        Parameter("--repo", help="GitHub owner/repo to search (repeatable, for --todo)."),
    ] = []
    check: Annotated[
        bool,
        Parameter(help="Show file paths and existence, then exit."),
    ] = False
    json_output: Annotated[
        bool,
        Parameter("--json", help="Output JSON instead of human-readable text."),
    ] = False
    replace: Annotated[
        bool,
        Parameter(help="Overwrite existing note/analysis files."),
    ] = False
    summary: Annotated[
        bool,
        Parameter(help="Include the summary (md) file."),
    ] = False
    note: Annotated[
        bool,
        Parameter(help="Include the user-notes file."),
    ] = False
    analysis: Annotated[
        bool,
        Parameter(help="Include the agent-analysis (cursor) file."),
    ] = False
    dest_dir: Annotated[
        str | None,
        Parameter(help="Override output directory."),
    ] = None


class JiraArgs(BaseModel):
    """Arguments for the ``jira`` subcommand."""

    key: Annotated[
        str | None,
        Parameter(help="Jira issue key or browse URL (required unless --todo)."),
    ] = None
    todo: Annotated[
        bool,
        Parameter(help="List open issues matching a JQL query."),
    ] = False
    jql: Annotated[
        str | None,
        Parameter(help="JQL query for --todo (overrides config)."),
    ] = None
    check: Annotated[
        bool,
        Parameter(help="Show file paths and existence, then exit."),
    ] = False
    json_output: Annotated[
        bool,
        Parameter("--json", help="Output JSON instead of human-readable text."),
    ] = False
    replace: Annotated[
        bool,
        Parameter(help="Overwrite existing note/analysis files."),
    ] = False
    summary: Annotated[
        bool,
        Parameter(help="Include the summary (md) file."),
    ] = False
    note: Annotated[
        bool,
        Parameter(help="Include the user-notes file."),
    ] = False
    analysis: Annotated[
        bool,
        Parameter(help="Include the agent-analysis (cursor) file."),
    ] = False
    dest_dir: Annotated[
        str | None,
        Parameter(help="Override output directory."),
    ] = None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


_DEFAULT_GH_ARGS = GitHubArgs()


@app.command
def github(args: Annotated[GitHubArgs, Parameter(name="*")] = _DEFAULT_GH_ARGS) -> None:
    """Create note files for a GitHub issue or PR.

    Fetches data from the GitHub API and renders note files in Logseq
    format.

    Use ``--todo --org <org> [--repo <owner/repo>]`` to list open
    issues/PRs you are involved in.
    Use ``--check`` to inspect file paths without fetching.
    Use ``--json`` to get machine-readable output (no files written).
    Use ``--summary``, ``--note``, ``--analysis`` to select which files
    to generate.
    Use ``--replace`` to overwrite existing note/analysis files
    (summary is always overwritten).
    """
    cfg = _get_config()

    if args.todo:
        if not args.org and not args.repo_filter:
            sys.stderr.write("Error: --todo requires at least one --org or --repo.\n")
            raise SystemExit(1)
        items = github_api.fetch_todo(
            orgs=args.org,
            repos=args.repo_filter,
            token=cfg.github.token,
        )
        if args.json_output:
            out = [item.model_dump() for item in items]
            sys.stdout.write(json.dumps(out, indent=2) + "\n")
        else:
            for item in items:
                sys.stdout.write(item.url + "\n")
        return

    if not args.url:
        sys.stderr.write("Error: a GitHub URL is required (or use --todo).\n")
        raise SystemExit(1)

    ref = GitHubRef.from_url(args.url)
    dest = args.dest_dir or cfg.dest_dir

    if args.check:
        triplet = writer_check(ref, dest)
        if args.json_output:
            sys.stdout.write(triplet.model_dump_json(indent=2) + "\n")
        else:
            sys.stdout.write(triplet.format_table() + "\n")
        return

    kinds = _resolve_kinds(
        summary=args.summary,
        note=args.note,
        analysis=args.analysis,
    )
    content = github_api.fetch(ref, token=cfg.github.token)

    if args.json_output:
        rendered = writer.render(content, ref, dest, kinds=kinds)
        out = {k: v.model_dump() for k, v in rendered.items()}
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return

    writer.write(content, ref, dest, kinds=kinds, replace=args.replace)


_DEFAULT_JIRA_ARGS = JiraArgs()


@app.command
def jira(args: Annotated[JiraArgs, Parameter(name="*")] = _DEFAULT_JIRA_ARGS) -> None:
    """Create note files for a Jira issue.

    Fetches data from the Jira API and renders note files in Logseq
    format.

    Use ``--todo [--jql QUERY]`` to list issues matching a JQL query.
    Use ``--check`` to inspect file paths without fetching.
    Use ``--json`` to get machine-readable output (no files written).
    Use ``--summary``, ``--note``, ``--analysis`` to select which files
    to generate.
    Use ``--replace`` to overwrite existing note/analysis files
    (summary is always overwritten).
    """
    cfg = _get_config()

    if args.todo:
        jql = args.jql if args.jql is not None else cfg.jira.jql
        items = jira_api.fetch_todo(
            endpoint=cfg.jira.endpoint,
            jql=jql,
            email=cfg.jira.email,
            token=cfg.jira.token,
        )
        if args.json_output:
            out = [item.model_dump() for item in items]
            sys.stdout.write(json.dumps(out, indent=2) + "\n")
        else:
            for item in items:
                sys.stdout.write(item.url + "\n")
        return

    if not args.key:
        sys.stderr.write("Error: a Jira key is required (or use --todo).\n")
        raise SystemExit(1)

    ref = JiraRef.from_string(args.key, default_endpoint=cfg.jira.endpoint)
    dest = args.dest_dir or cfg.dest_dir

    if args.check:
        triplet = writer_check(ref, dest)
        if args.json_output:
            sys.stdout.write(triplet.model_dump_json(indent=2) + "\n")
        else:
            sys.stdout.write(triplet.format_table() + "\n")
        return

    kinds = _resolve_kinds(
        summary=args.summary,
        note=args.note,
        analysis=args.analysis,
    )
    content = jira_api.fetch(
        ref,
        email=cfg.jira.email,
        token=cfg.jira.token,
        github_field=cfg.jira.github_field,
    )

    if args.json_output:
        rendered = writer.render(content, ref, dest, kinds=kinds)
        out = {k: v.model_dump() for k, v in rendered.items()}
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return

    writer.write(content, ref, dest, kinds=kinds, replace=args.replace)
    _chain_github(content, dest, cfg=cfg, replace=args.replace)


def _chain_github(
    content: NoteContent,
    dest: str,
    *,
    cfg: AppConfig,
    replace: bool,
) -> None:
    """If *content* references a GitHub PR/issue, fetch and write its notes.

    Args:
        content: Jira note content (may contain ``extra["github_url"]``).
        dest: Output directory.
        cfg: Application config (provides the GitHub token).
        replace: Whether to overwrite existing files.
    """
    gh_url = content.extra.get("github_url")
    if not gh_url:
        return
    try:
        gh_ref = GitHubRef.from_url(gh_url)
    except ValueError:
        return
    gh_content = github_api.fetch(gh_ref, token=cfg.github.token)
    writer.write(gh_content, gh_ref, dest, replace=replace)


def main() -> None:
    """Entry point for the ``notegraph`` command."""
    try:
        app.meta()
    except (GitHubFetchError, JiraFetchError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        raise SystemExit(1) from None
