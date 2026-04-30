"""Notegraph CLI — cyclopts-based command-line interface.

Usage::

    notegraph [--config PATH] fetch --source github|jira <URL_OR_KEY> [OPTIONS]
    notegraph [--config PATH] todo  [--source github|jira] [OPTIONS]

Global options (before the subcommand):

    --config PATH         Path to TOML config file
                          (default: ~/.config/notegraph/config.toml).
    -v, --verbose         Debug logging for all commands.
    --dry-run             Preview without writing notes/worktodo or Vikunja mutations.

``fetch`` options:

    --source github|jira  Source platform (required).
    <URL_OR_KEY>          GitHub URL or Jira key / browse URL (required).
    --check               Show file paths and existence, then exit.
    --json                Output JSON instead of human-readable text.
    --summary             Include the summary (md) file.
    --note                Include the user-notes file.
    --analysis            Include the agent-analysis (cursor) file.
    --no-summary          Exclude the summary file.
    --no-note             Exclude the user-notes file.
    --no-analysis         Exclude the agent-analysis file.
    --replace             Overwrite existing note/analysis files.
    --dest-dir DIR        Override output directory.

``todo`` options:

    --source github|jira  Filter to one source (default: both).
    --json                Output JSON array.
    --sync                Write worktodo.md and fetch note triplets (Logseq).
    --vikunja             Push waiting items from Jira/GitHub into Vikunja.
    --leave-vikunja-stale Keep Vikunja mirrors open when gone upstream (default: mark done).
    --org ORG             GitHub org to search (repeatable; overrides config).
    --repo OWNER/REPO     GitHub repo to search (repeatable; overrides config).
    --jql QUERY           Jira JQL override (listing, --sync, and --vikunja).
    --dest-dir DIR        Override output directory.

When using ``--vikunja``, the default is to **mark Vikunja tasks done** if they
drop off the Jira/GitHub waiting query (so Vikunja matches upstream). Pass
``--leave-vikunja-stale`` to **leave those mirrors open** instead.

Examples::

    notegraph fetch --source github https://github.com/org/repo/pull/1
    notegraph fetch --source github --check https://github.com/org/repo/pull/1
    notegraph fetch --source jira RUN-3555
    notegraph todo
    notegraph todo --source github --org containers
    notegraph todo --json
    notegraph todo --sync
    notegraph todo --vikunja
    notegraph todo --sync --vikunja
    notegraph --dry-run todo --vikunja
    notegraph -v todo --vikunja --jql 'assignee = currentUser() ORDER BY updated DESC'
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tomllib
from pathlib import Path
from typing import Annotated, Any, Literal

import requests
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
    TodoItem,
)
from notegraph.todo import merge_worktodo, parse_worktodo, write_worktodo
from notegraph.writer import check as writer_check

logger = logging.getLogger(__name__)

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
    orgs: list[str] = []
    repos: list[str] = []


class LogseqConfig(BaseModel):
    """Logseq output configuration."""

    graph_dir: str = "~/Documents/Logseq/Work/pages"


class VikunjaConfig(BaseModel):
    """Vikunja target + sync defaults for ``notegraph todo --vikunja``."""

    base_url: str = "http://127.0.0.1:3456"
    token: str = ""
    #: Optional GitHub ``q`` string for Vikunja sync. Empty means use
    #: :func:`~notegraph.github.fetch_todo` with ``[github].orgs`` / ``repos``
    #: (same as ``notegraph todo``).
    github_search_query: str = ""
    #: ``str.format`` template for the Vikunja **project title** tasks are filed under.
    #: Placeholders: ``repo`` (``owner/repo``), ``org``, ``repo_name``.
    github_project_template: str = "{repo}"
    #: Same for Jira. Placeholders: ``project_key`` (e.g. ``RUN``), ``issue_key``
    #: (e.g. ``RUN-123``).
    jira_project_template: str = "{project_key}"


class AppConfig(BaseModel):
    """Full application config, assembled from TOML + env vars.

    Not directly a CLI parameter — built inside command handlers from
    the ``--config`` path.
    """

    jira: JiraConfig = JiraConfig()
    github: GitHubConfig = GitHubConfig()
    logseq: LogseqConfig = LogseqConfig()
    vikunja: VikunjaConfig = VikunjaConfig()

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
    vikunja = data.setdefault("vikunja", {})

    if token := os.environ.get("JIRA_TOKEN"):
        jira["token"] = token
    if email := os.environ.get("JIRA_EMAIL"):
        jira["email"] = email
    if endpoint := os.environ.get("JIRA_ENDPOINT"):
        jira["endpoint"] = endpoint
    if token := os.environ.get("GITHUB_TOKEN"):
        github["token"] = token
    if token := os.environ.get("VIKUNJA_TOKEN"):
        vikunja["token"] = token
    if base_url := os.environ.get("VIKUNJA_BASE_URL"):
        vikunja["base_url"] = base_url


# ---------------------------------------------------------------------------
# Global state — populated by the meta launcher, read by subcommands
# ---------------------------------------------------------------------------

_cfg: AppConfig | None = None
_config_path: Path | None = None
_cli_dry_run: bool = False


def _get_config_path() -> Path:
    """Return the config path from the meta launcher, or the default."""
    if _config_path is not None:
        return _config_path
    return DEFAULT_CONFIG_PATH


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
    verbose: Annotated[
        bool,
        Parameter("--verbose", alias="-v", help="Enable debug logging."),
    ] = False,
    dry_run: Annotated[
        bool,
        Parameter(
            "--dry-run",
            help="Preview without writing notes / worktodo, or without Vikunja writes.",
        ),
    ] = False,
) -> None:
    """Launch notegraph with global options."""
    global _cfg, _config_path, _cli_dry_run  # noqa: PLW0603
    _cfg = load_config(config)
    _config_path = config
    _cli_dry_run = dry_run
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(message)s",
        force=True,
    )
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


class FetchArgs(BaseModel):
    """Arguments for the ``fetch`` subcommand."""

    target: Annotated[
        str,
        Parameter(help="GitHub URL or Jira issue key / browse URL."),
    ] = ""
    source: Annotated[
        Literal["github", "jira"],
        Parameter(help="Source platform: github or jira."),
    ] = "github"
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


class TodoArgs(BaseModel):
    """Arguments for the ``todo`` subcommand."""

    source: Annotated[
        Literal["github", "jira"] | None,
        Parameter(help="Filter to one source (default: both)."),
    ] = None
    json_output: Annotated[
        bool,
        Parameter("--json", help="Output JSON array."),
    ] = False
    sync: Annotated[
        bool,
        Parameter(help="Write worktodo.md and fetch note triplets for each item."),
    ] = False
    vikunja: Annotated[
        bool,
        Parameter(
            "--vikunja",
            help=(
                "Push Jira/GitHub waiting items into Vikunja "
                "(uses [vikunja] / [github] / [jira]; not filtered by --source)."
            ),
        ),
    ] = False
    leave_vikunja_stale: Annotated[
        bool,
        Parameter(
            "--leave-vikunja-stale",
            help=(
                "With --vikunja: keep mirrored Vikunja tasks open when they disappear "
                "from Jira/GitHub (default: mark those mirrors done)."
            ),
        ),
    ] = False
    org: Annotated[
        list[str],
        Parameter(help="GitHub org to search (repeatable, overrides config)."),
    ] = []
    repo_filter: Annotated[
        list[str],
        Parameter("--repo", help="GitHub owner/repo to search (repeatable, overrides config)."),
    ] = []
    jql: Annotated[
        str | None,
        Parameter(help="Jira JQL override."),
    ] = None
    dest_dir: Annotated[
        str | None,
        Parameter(help="Override output directory."),
    ] = None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


_DEFAULT_FETCH_ARGS = FetchArgs()


@app.command
def fetch(args: Annotated[FetchArgs, Parameter(name="*")] = _DEFAULT_FETCH_ARGS) -> None:
    """Fetch a single issue/PR and write note triplets.

    Use ``--source github`` with a full GitHub URL, or
    ``--source jira`` with a Jira key or browse URL.
    Use ``--check`` to inspect file paths without fetching.
    Use ``--json`` to get machine-readable output (no files written).
    Use ``--summary``, ``--note``, ``--analysis`` to select which files
    to generate.
    Use ``--replace`` to overwrite existing note/analysis files
    (summary is always overwritten).
    """
    cfg = _get_config()

    if not args.target:
        sys.stderr.write("Error: a target URL or key is required.\n")
        raise SystemExit(1)

    dest = args.dest_dir or cfg.dest_dir

    if args.source == "github":
        _fetch_github(args, cfg, dest)
    else:
        _fetch_jira(args, cfg, dest)


def _fetch_github(args: FetchArgs, cfg: AppConfig, dest: str) -> None:
    ref = GitHubRef.from_url(args.target)

    if args.check:
        triplet = writer_check(ref, dest)
        if args.json_output:
            sys.stdout.write(triplet.model_dump_json(indent=2) + "\n")
        else:
            sys.stdout.write(triplet.format_table() + "\n")
        return

    kinds = _resolve_kinds(summary=args.summary, note=args.note, analysis=args.analysis)
    content = github_api.fetch(ref, token=cfg.github.token)

    if args.json_output:
        rendered = writer.render(content, ref, dest, kinds=kinds)
        out = {k: v.model_dump() for k, v in rendered.items()}
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return

    if _cli_dry_run:
        sys.stderr.write(f"[dry-run] would write notes for GitHub {args.target}\n")
        return

    writer.write(content, ref, dest, kinds=kinds, replace=args.replace)


def _fetch_jira(args: FetchArgs, cfg: AppConfig, dest: str) -> None:
    ref = JiraRef.from_string(args.target, default_endpoint=cfg.jira.endpoint)

    if args.check:
        triplet = writer_check(ref, dest)
        if args.json_output:
            sys.stdout.write(triplet.model_dump_json(indent=2) + "\n")
        else:
            sys.stdout.write(triplet.format_table() + "\n")
        return

    kinds = _resolve_kinds(summary=args.summary, note=args.note, analysis=args.analysis)
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

    if _cli_dry_run:
        sys.stderr.write(f"[dry-run] would write notes for Jira {args.target}\n")
        return

    writer.write(content, ref, dest, kinds=kinds, replace=args.replace)
    _chain_github(content, dest, cfg=cfg, replace=args.replace)


_DEFAULT_TODO_ARGS = TodoArgs()


@app.command
def todo(args: Annotated[TodoArgs, Parameter(name="*")] = _DEFAULT_TODO_ARGS) -> None:
    """List open items and optionally sync Logseq worktodo or Vikunja.

    Without flags, prints URLs from both GitHub and Jira.
    Use ``--source`` to filter to one platform.
    Use ``--json`` for machine-readable output (cannot combine with ``--vikunja``).
    Use ``--sync`` to write ``worktodo.md`` and fetch/write note files
    for every listed item.
    Use ``--vikunja`` to mirror waiting items into Vikunja (see config ``[vikunja]``).
    ``--sync`` and ``--vikunja`` may be combined.
    """
    cfg = _get_config()
    dest = args.dest_dir or cfg.dest_dir

    if args.json_output and args.vikunja:
        sys.stderr.write("Error: --json cannot be combined with --vikunja.\n")
        raise SystemExit(1)

    if args.json_output:
        items = _collect_todo_items(args, cfg)
        out = [item.model_dump() for item in items]
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return

    items: list[TodoItem] = []
    if args.sync or not args.vikunja:
        items = _collect_todo_items(args, cfg)

    if args.sync:
        _sync_worktodo(items, dest, cfg)

    if args.vikunja:
        from notegraph.vikunja_sync import run_sync  # noqa: PLC0415

        try:
            code = run_sync(
                config_path=_get_config_path(),
                dry_run=_cli_dry_run,
                complete_stale=not args.leave_vikunja_stale,
                jira_jql=args.jql,
            )
        except requests.HTTPError:
            code = 1
        if code != 0:
            raise SystemExit(code)

    if args.sync or args.vikunja:
        return

    for item in items:
        sys.stdout.write(item.url + "\n")


def _collect_todo_items(
    args: TodoArgs,
    cfg: AppConfig,
) -> list:
    """Gather todo items from GitHub, Jira, or both.

    Args:
        args: Parsed todo arguments.
        cfg: Application config.

    Returns:
        Combined list of ``TodoItem`` instances.
    """
    items: list[TodoItem] = []

    if args.source in (None, "github"):
        orgs = args.org or cfg.github.orgs
        repos = args.repo_filter or cfg.github.repos
        if orgs or repos:
            items.extend(
                github_api.fetch_todo(orgs=orgs, repos=repos, token=cfg.github.token)
            )
        elif args.source == "github":
            sys.stderr.write("Error: --source github requires at least one --org or --repo.\n")
            raise SystemExit(1)

    if args.source in (None, "jira"):
        jql = args.jql if args.jql is not None else cfg.jira.jql
        if jql or args.source == "jira":
            items.extend(
                jira_api.fetch_todo(
                    endpoint=cfg.jira.endpoint,
                    jql=jql,
                    email=cfg.jira.email,
                    token=cfg.jira.token,
                )
            )

    return items


def _sync_worktodo(
    items: list,
    dest: str,
    cfg: AppConfig,
) -> None:
    """Write ``worktodo.md`` and fetch note triplets for every item.

    Args:
        items: All collected todo items.
        dest: Output directory.
        cfg: Application config.
    """
    if _cli_dry_run:
        sys.stderr.write(
            f"[dry-run] would write worktodo and fetch notes for {len(items)} item(s)\n",
        )
        return

    worktodo_path = Path(dest) / "worktodo.md"
    existing = parse_worktodo(worktodo_path)
    merged = merge_worktodo(existing, items)
    write_worktodo(merged, worktodo_path)
    sys.stderr.write(f"Wrote {worktodo_path}\n")

    for item in items:
        try:
            if item.source == "github":
                ref = GitHubRef.from_url(item.url)
                content = github_api.fetch(ref, token=cfg.github.token)
                writer.write(content, ref, dest, replace=False)
            elif item.source == "jira":
                ref = JiraRef.from_string(item.url, default_endpoint=cfg.jira.endpoint)
                content = jira_api.fetch(
                    ref,
                    email=cfg.jira.email,
                    token=cfg.jira.token,
                    github_field=cfg.jira.github_field,
                )
                writer.write(content, ref, dest, replace=False)
                _chain_github(content, dest, cfg=cfg, replace=False)
        except (GitHubFetchError, JiraFetchError, ValueError) as exc:
            logger.warning("Skipping %s: %s", item.url, exc)


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
