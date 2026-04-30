r"""Sync Jira and GitHub "waiting on me" items into Vikunja projects.

CLI entry: ``notegraph todo --vikunja`` (see :mod:`notegraph.cli`).

Tasks are filed under Vikunja project titles derived from ``[vikunja]`` templates
(default ``{repo}`` for GitHub and ``{project_key}`` for Jira). Upserts match a
hidden HTML marker in the description using a stable slug id (e.g.
``github-org-repo-issue-12``, ``github-org-repo-pull-12``, ``jira-run-100``).
Legacy markers ``github:owner/repo#N`` / ``jira:KEY`` normalize when read so
existing tasks still match. Each sync updates Vikunja when title, description, or
start date differs; stale upstream items can be marked done.

**Vikunja task titles** are stable identifiers only: Jira **issue keys** (e.g.
``RUN-3555``) and GitHub **sync slugs** (``github-org-repo-issue-N`` /
``…-pull-N``). Human summaries appear in the task description. Descriptions do
not include Logseq files — run ``todo --sync`` for note triplets.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import requests

from notegraph import github as github_api
from notegraph import jira as jira_api
from notegraph.cli import AppConfig, load_config
from notegraph.github import FetchError as GitHubFetchError
from notegraph.jira import FetchError as JiraFetchError

if TYPE_CHECKING:
    from pathlib import Path

    from notegraph.schema import TodoItem

logger = logging.getLogger(__name__)

_SYNC_RE = re.compile(r"<!--\s*notegraph-sync\s+id=([^>\s]+)\s*-->")
_JIRA_KEY_FROM_URL = re.compile(r"/browse/([A-Z][A-Z0-9]*-\d+)")
_GH_ISSUE_NUM_FROM_URL = re.compile(r"/(?:pull|issues)/(\d+)(?:$|[?#])")
_LEGACY_MARKER_GITHUB = re.compile(r"^github:([^/]+)/([^#]+)#(\d+)$")
_LEGACY_MARKER_JIRA = re.compile(r"^jira:([A-Za-z][A-Za-z0-9]*-\d+)$")

_DEFAULT_JIRA_JQL = "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC"
_DEFAULT_GITHUB_PROJECT_TEMPLATE = "{repo}"
_DEFAULT_JIRA_PROJECT_TEMPLATE = "{project_key}"

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VIKUNJA_ZERO_DATE = "0001-01-01T00:00:00Z"


_DUE_DATE_OFFSET = datetime.timedelta(days=7)


def _normalize_vikunja_date(value: str) -> str:
    """Convert bare ``YYYY-MM-DD`` to ``YYYY-MM-DDT00:00:00Z`` for Vikunja."""
    if _DATE_ONLY_RE.match(value):
        return f"{value}T00:00:00Z"
    return value


def _default_due_date(start_iso: str) -> str:
    """Return *start_iso* + 7 days in Vikunja datetime format.

    *start_iso* must already be normalized (``YYYY-MM-DDTHH:MM:SSZ``).
    Returns ``""`` when the input is empty or unparseable.
    """
    if not start_iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    due = dt + _DUE_DATE_OFFSET
    return due.strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_github_org_repo(full: str) -> tuple[str, str]:
    """Split ``owner/repo`` into ``(owner, repo_name)``."""
    if "/" in full:
        org, repo_name = full.split("/", 1)
        return org, repo_name
    return "", full


def _slug_segment(segment: str) -> str:
    """Lowercase URL-ish token for sync ids (hyphen-separated)."""
    s = segment.strip().lower().replace("_", "-")
    out = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", out).strip("-") or "x"


def _github_sync_slug(repo_full: str, number: str, *, is_pull: bool) -> str:
    """Stable id like ``github-org-repo-issue-42`` or ``...-pull-42``."""
    org, rn = _split_github_org_repo(repo_full)
    kind = "pull" if is_pull else "issue"
    return f"github-{_slug_segment(org)}-{_slug_segment(rn)}-{kind}-{number}"


def _jira_sync_slug(issue_key: str) -> str:
    """Stable id like ``jira-run-123``."""
    return f"jira-{_slug_segment(issue_key)}"


def _github_pull_hint_in_description(description: str, number: str) -> bool:
    """True if *description* links this item as a GitHub pull request."""
    return bool(
        re.search(
            rf"github\.com/[^/\s]+/[^/\s]+/pull/{re.escape(number)}\b",
            description,
        ),
    )


def _canonical_sync_id(raw: str, description: str) -> str:
    """Normalize marker ids so legacy ``github:…`` / ``jira:…`` match new slugs."""
    if raw.startswith(("github-", "jira-")):
        return raw
    mj = _LEGACY_MARKER_JIRA.match(raw)
    if mj:
        return _jira_sync_slug(mj.group(1))
    mg = _LEGACY_MARKER_GITHUB.match(raw)
    if mg:
        org, repo, num = mg.group(1), mg.group(2), mg.group(3)
        is_pull = _github_pull_hint_in_description(description, num)
        return _github_sync_slug(f"{org}/{repo}", num, is_pull=is_pull)
    return raw


def _format_vikunja_project_title(template: str, mapping: dict[str, str]) -> str:
    """Apply ``str.format`` for Vikunja project titles."""
    try:
        return template.format(**mapping).strip()
    except (KeyError, ValueError):
        logger.exception(
            "Bad Vikunja project template %r (keys: %s)",
            template,
            sorted(mapping.keys()),
        )
        msg = "invalid Vikunja project template"
        raise ValueError(msg) from None


def _is_sync_owned_marker(sync_id: str) -> bool:
    """True if this sync id was created by ``notegraph todo --vikunja``."""
    return sync_id.startswith(("jira-", "github-", "jira:", "github:"))


def _normalize_vikunja_token(raw: str) -> str:
    """Strip whitespace and a duplicated ``Bearer `` prefix if present."""
    token = raw.strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def _vikunja_require_ok(response: requests.Response) -> None:
    """Raise :exc:`requests.HTTPError` on failed Vikunja responses."""
    if not response.ok:
        logger.error(
            "Vikunja %s %s → %s: %s",
            response.request.method,
            response.request.url,
            response.status_code,
            response.text[:500],
        )
    response.raise_for_status()


@dataclass(frozen=True)
class WaitingItem:
    """A unit of work mirrored into Vikunja."""

    sync_id: str
    title: str
    description: str
    vikunja_project_title: str
    start_date: str = ""


def _sync_marker(sync_id: str) -> str:
    """Return the HTML comment used to identify a managed Vikunja task."""
    return f"<!-- notegraph-sync id={sync_id} -->"


def _extract_sync_id(description: str | None) -> str | None:
    """Parse canonical sync id from a task description marker, if present."""
    if not description:
        return None
    match = _SYNC_RE.search(description)
    if not match:
        return None
    raw = match.group(1).strip()
    return _canonical_sync_id(raw, description)


def _waiting_from_jira_todo(item: TodoItem, *, project_template: str) -> WaitingItem | None:
    """Build a Vikunja waiting row from a Jira :class:`TodoItem`."""
    match = _JIRA_KEY_FROM_URL.search(item.url)
    if not match:
        logger.warning("Skipping Jira todo with unexpected URL: %s", item.url)
        return None
    key = match.group(1)
    project = item.repo or "UNKNOWN"
    sync_id = _jira_sync_slug(key)
    marker = _sync_marker(sync_id)
    summary = str(item.title).strip()
    summary_block = f"\n**Summary:** {summary}\n\n" if summary else "\n"
    description = (
        f"{marker}\n\n"
        f"[{key}]({item.url})"
        f"{summary_block}"
        f"**Status:** {item.state} · **Type:** {item.kind}\n"
    )
    vik_title = _format_vikunja_project_title(
        project_template,
        {"project_key": project, "issue_key": key},
    )
    return WaitingItem(
        sync_id=sync_id,
        title=key[:500],
        description=description,
        vikunja_project_title=vik_title,
        start_date=(item.start_date or "").strip(),
    )


def _waiting_from_github_todo(item: TodoItem, *, project_template: str) -> WaitingItem | None:
    """Build a Vikunja waiting row from a GitHub :class:`TodoItem`."""
    if not item.repo:
        logger.warning("Skipping GitHub todo missing repo: %s", item.url)
        return None
    match = _GH_ISSUE_NUM_FROM_URL.search(item.url)
    if not match:
        logger.warning("Skipping GitHub todo with unexpected URL: %s", item.url)
        return None
    number = match.group(1)
    sync_id = _github_sync_slug(
        item.repo,
        number,
        is_pull=item.kind == "pull_request",
    )
    marker = _sync_marker(sync_id)
    kind_label = "Pull request" if item.kind == "pull_request" else "Issue"
    summary = str(item.title).strip()
    summary_block = f"\n**Summary:** {summary}\n\n" if summary else "\n"
    description = (
        f"{marker}\n\n"
        f"[{sync_id}]({item.url})"
        f"{summary_block}"
        f"**{kind_label}** · **Repo:** `{item.repo}` · **State:** {item.state}\n"
    )
    org, repo_name = _split_github_org_repo(item.repo)
    vik_title = _format_vikunja_project_title(
        project_template,
        {"repo": item.repo, "org": org, "repo_name": repo_name},
    )
    return WaitingItem(
        sync_id=sync_id,
        title=sync_id[:500],
        description=description,
        vikunja_project_title=vik_title,
        start_date=(item.start_date or "").strip(),
    )


def _collect_jira_waiting(cfg: AppConfig, jql: str) -> tuple[list[WaitingItem], int]:
    """Return Vikunja rows from Jira via :func:`~notegraph.jira.fetch_todo`."""
    rows: list[WaitingItem] = []
    if not (cfg.jira.endpoint and cfg.jira.email and cfg.jira.token):
        logger.warning("Skipping Jira: missing endpoint, email, or token.")
        return rows, 0
    j_tpl = (cfg.vikunja.jira_project_template or _DEFAULT_JIRA_PROJECT_TEMPLATE).strip()
    try:
        todos = jira_api.fetch_todo(
            endpoint=cfg.jira.endpoint,
            jql=jql,
            email=cfg.jira.email,
            token=cfg.jira.token,
        )
    except JiraFetchError as exc:
        logger.warning("Jira fetch failed: %s", exc)
        return rows, 1
    for todo in todos:
        try:
            row = _waiting_from_jira_todo(todo, project_template=j_tpl)
        except ValueError:
            return rows, 1
        if row:
            rows.append(row)
    logger.info("Jira: %s issue(s).", len(rows))
    return rows, 0


def _collect_github_waiting(cfg: AppConfig, gh_query: str) -> tuple[list[WaitingItem], int]:
    """Return Vikunja rows from GitHub via ``fetch_todo`` / ``fetch_todo_search``."""
    rows: list[WaitingItem] = []
    if not cfg.github.token:
        if gh_query or cfg.github.orgs or cfg.github.repos:
            logger.warning("Skipping GitHub: no github.token / GITHUB_TOKEN.")
        return rows, 0
    try:
        if gh_query:
            todos = github_api.fetch_todo_search(query=gh_query, token=cfg.github.token)
        elif cfg.github.orgs or cfg.github.repos:
            todos = github_api.fetch_todo(
                orgs=cfg.github.orgs,
                repos=cfg.github.repos,
                token=cfg.github.token,
            )
        else:
            logger.warning(
                "Skipping GitHub: no [vikunja].github_search_query and no "
                "[github].orgs/repos (same scopes as ``notegraph todo``).",
            )
            todos = []
    except GitHubFetchError as exc:
        logger.warning("GitHub fetch failed: %s", exc)
        return rows, 1
    gh_tpl = (cfg.vikunja.github_project_template or _DEFAULT_GITHUB_PROJECT_TEMPLATE).strip()
    for todo in todos:
        try:
            row = _waiting_from_github_todo(todo, project_template=gh_tpl)
        except ValueError:
            return rows, 1
        if row:
            rows.append(row)
    logger.info("GitHub: %s item(s).", len(rows))
    return rows, 0


class VikunjaClient:
    """Thin Vikunja REST v1 client (Bearer token)."""

    def __init__(
        self,
        base_api: str,
        token: str,
        *,
        session: requests.Session | None = None,
    ) -> None:
        """Initialize with API root (``…/api/v1``) and bearer token."""
        self.base = base_api.rstrip("/")
        self._projects_cache: list[dict[str, Any]] | None = None
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
        )

    def verify_auth(self) -> None:
        """Verify the API token with ``GET /user``."""
        response = self.session.get(f"{self.base}/user", timeout=30)
        _vikunja_require_ok(response)

    def list_projects(self) -> list[dict[str, Any]]:
        """Return all projects visible to the token (cached after first call)."""
        if self._projects_cache is not None:
            return self._projects_cache
        response = self.session.get(f"{self.base}/projects", timeout=60)
        _vikunja_require_ok(response)
        data = response.json()
        self._projects_cache = data if isinstance(data, list) else []
        logger.debug("Loaded %s Vikunja project(s).", len(self._projects_cache))
        return self._projects_cache

    def ensure_project(self, title: str, *, dry_run: bool) -> int | None:
        """Return project id, creating the project if needed."""
        for project in self.list_projects():
            if project.get("title") == title:
                return int(project["id"])
        if dry_run:
            logger.info("Would create Vikunja project %r", title)
            return None
        logger.debug("Creating Vikunja project %r", title)
        response = self.session.put(
            f"{self.base}/projects",
            json={"title": title, "parent_project_id": 0},
            timeout=60,
        )
        _vikunja_require_ok(response)
        created = response.json()
        pid = int(created["id"])
        self._projects_cache = None
        return pid

    def iter_tasks(self, *, per_page: int = 100) -> list[dict[str, Any]]:
        """Paginate through all tasks the user can see.

        Tries ``GET /tasks`` first. If the server returns 404, falls back to
        ``GET /tasks/all`` (older Vikunja, see `go-vikunja/vikunja#1984`).
        An empty list from ``/tasks`` is accepted as-is — no fallback needed.
        """
        try:
            return self._fetch_paginated_task_list("/tasks", per_page=per_page)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == HTTPStatus.NOT_FOUND:
                logger.debug("GET /tasks returned 404; trying legacy /tasks/all.")
                return self._fetch_paginated_task_list("/tasks/all", per_page=per_page)
            raise

    def _fetch_paginated_task_list(
        self,
        path: str,
        *,
        per_page: int,
        timeout: int = 30,
    ) -> list[dict[str, Any]]:
        """GET *path* with ``page`` / ``per_page`` until a short page or empty."""
        page = 1
        out: list[dict[str, Any]] = []
        while True:
            logger.debug("GET %s page=%s per_page=%s", path, page, per_page)
            response = self.session.get(
                f"{self.base}{path}",
                params={"page": page, "per_page": per_page},
                timeout=timeout,
            )
            _vikunja_require_ok(response)
            batch = response.json()
            if batch is None:
                batch = []
            if not isinstance(batch, list):
                logger.warning(
                    "Unexpected JSON from %s (wanted list, got %s); stopping pagination.",
                    path,
                    type(batch).__name__,
                )
                break
            if not batch:
                break
            out.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return out

    def create_task(
        self,
        project_id: int,
        task: dict[str, Any],
        *,
        dry_run: bool,
    ) -> dict[str, Any] | None:
        """Create a task inside *project_id*."""
        if dry_run:
            logger.info("Would create task in project %s: %r", project_id, task.get("title"))
            return None
        task_body = dict(task)
        task_body["project_id"] = project_id
        response = self.session.put(
            f"{self.base}/projects/{project_id}/tasks",
            json=task_body,
            timeout=60,
        )
        _vikunja_require_ok(response)
        return response.json()

    def update_task(
        self,
        task_id: int,
        task: dict[str, Any],
        *,
        dry_run: bool,
    ) -> dict[str, Any] | None:
        """Update an existing task by id."""
        if dry_run:
            logger.info("Would update task %s: %r", task_id, task.get("title"))
            return None
        response = self.session.post(
            f"{self.base}/tasks/{task_id}",
            json=task,
            timeout=60,
        )
        _vikunja_require_ok(response)
        return response.json()


def _build_task_indexes(
    all_tasks: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, dict[str, Any]]], list[dict[str, Any]]]:
    """Index tasks by project and sync id; collect managed tasks for stale completion."""
    tasks_by_project: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    managed_tasks: list[dict[str, Any]] = []
    for task in all_tasks:
        desc = task.get("description") or ""
        sid = _extract_sync_id(desc)
        if not sid:
            continue
        pid = int(task["project_id"])
        tasks_by_project[pid][sid] = task
        if _is_sync_owned_marker(sid):
            managed_tasks.append(task)
    return tasks_by_project, managed_tasks


def _upsert_project_items(
    client: VikunjaClient,
    by_project: dict[str, list[WaitingItem]],
    project_ids: dict[str, int],
    tasks_by_project: dict[int, dict[str, dict[str, Any]]],
    *,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Create or update Vikunja tasks for each waiting item.

    Returns:
        Counts ``(created, updated, unchanged)``.
    """
    created = updated = unchanged = 0
    for project_title, bucket in by_project.items():
        pid = project_ids.get(project_title)
        if pid is None:
            logger.debug(
                "Skipping project %r (no Vikunja project id — often dry-run create).",
                project_title,
            )
            continue
        existing = tasks_by_project.get(pid, {})
        for item in bucket:
            want_start = _normalize_vikunja_date((item.start_date or "").strip())
            if want_start == _VIKUNJA_ZERO_DATE:
                want_start = ""
            want_due = _default_due_date(want_start)
            task_payload: dict[str, Any] = {
                "title": item.title,
                "description": item.description,
                "done": False,
            }
            if want_start:
                task_payload["start_date"] = want_start
            if want_due:
                task_payload["due_date"] = want_due
            if item.sync_id in existing:
                current = existing[item.sync_id]
                tid = int(current["id"])
                cur_title = current.get("title")
                cur_desc = current.get("description") or ""
                cur_start = (current.get("start_date") or "").strip()
                cur_due = (current.get("due_date") or "").strip()
                if cur_start == _VIKUNJA_ZERO_DATE:
                    cur_start = ""
                if cur_due == _VIKUNJA_ZERO_DATE:
                    cur_due = ""
                needs_update = (
                    cur_title != item.title
                    or cur_desc != item.description
                    or cur_start != want_start
                    or cur_due != want_due
                )
                if needs_update:
                    update_body: dict[str, Any] = {
                        "id": tid,
                        "title": item.title,
                        "description": item.description,
                        "done": bool(current.get("done")),
                        "project_id": pid,
                    }
                    if want_start:
                        update_body["start_date"] = want_start
                    if want_due:
                        update_body["due_date"] = want_due
                    logger.debug(
                        "Update task id=%s sync_id=%s project=%r",
                        tid,
                        item.sync_id,
                        project_title,
                    )
                    client.update_task(tid, update_body, dry_run=dry_run)
                    updated += 1
                else:
                    logger.debug(
                        "Unchanged sync_id=%s project=%r",
                        item.sync_id,
                        project_title,
                    )
                    unchanged += 1
            else:
                logger.debug(
                    "Create task sync_id=%s project=%r",
                    item.sync_id,
                    project_title,
                )
                client.create_task(pid, task_payload, dry_run=dry_run)
                created += 1
    return created, updated, unchanged


def _complete_stale_managed_tasks(
    client: VikunjaClient,
    managed_tasks: list[dict[str, Any]],
    current_ids: set[str],
    *,
    dry_run: bool,
) -> int:
    """Mark managed Vikunja tasks done when their sync id is no longer upstream."""
    n_done = 0
    for task in managed_tasks:
        sid = _extract_sync_id(task.get("description") or "")
        if not sid:
            continue
        if sid in current_ids or task.get("done"):
            continue
        tid = int(task["id"])
        pid = int(task["project_id"])
        update_body = {
            "id": tid,
            "title": task.get("title") or "",
            "description": task.get("description") or "",
            "done": True,
            "project_id": pid,
        }
        logger.info("Completing stale managed task %s (%s)", tid, sid)
        client.update_task(tid, update_body, dry_run=dry_run)
        n_done += 1
    return n_done


def run_sync(
    *,
    config_path: Path,
    dry_run: bool,
    complete_stale: bool,
    jira_jql: str | None,
) -> int:
    """Run one sync pass. Returns a process exit code."""
    cfg = load_config(config_path)

    logger.debug(
        "Vikunja task titles are stable ids (issue key / github slug); summaries "
        "and links live in the description. Logseq triplets need todo --sync.",
    )

    vikunja_base = cfg.vikunja.base_url.strip().rstrip("/") or "http://127.0.0.1:3456"
    vikunja_api = f"{vikunja_base}/api/v1"
    vikunja_token = _normalize_vikunja_token(cfg.vikunja.token)
    if not vikunja_token:
        logger.error(
            "Set [vikunja].token in %s or export VIKUNJA_TOKEN.",
            config_path,
        )
        return 1

    client = VikunjaClient(vikunja_api, vikunja_token, session=requests.Session())
    client.verify_auth()

    jql = (jira_jql or os.environ.get("JIRA_JQL") or cfg.jira.jql or "").strip()
    if not jql:
        jql = _DEFAULT_JIRA_JQL

    gh_query = cfg.vikunja.github_search_query.strip()

    jira_waiting, jira_err = _collect_jira_waiting(cfg, jql)
    if jira_err:
        return 1
    github_waiting, gh_err = _collect_github_waiting(cfg, gh_query)
    if gh_err:
        return 1

    by_project: dict[str, list[WaitingItem]] = defaultdict(list)
    for item in (*jira_waiting, *github_waiting):
        by_project[item.vikunja_project_title].append(item)

    logger.info(
        "Resolving %s Vikunja project(s) from %s upstream item(s).",
        len(by_project),
        len(jira_waiting) + len(github_waiting),
    )
    project_ids: dict[str, int] = {}
    for title in by_project:
        pid = client.ensure_project(title, dry_run=dry_run)
        if pid is not None:
            project_ids[title] = pid

    logger.info("Fetching existing Vikunja tasks for dedup…")
    all_tasks = client.iter_tasks()
    tasks_by_project, managed_tasks = _build_task_indexes(all_tasks)

    current_ids = {item.sync_id for item in (*jira_waiting, *github_waiting)}
    upstream_n = len(jira_waiting) + len(github_waiting)
    logger.info(
        "Indexed %s Vikunja task(s); %s upstream waiting row(s).",
        len(all_tasks),
        upstream_n,
    )

    created, updated, unchanged = _upsert_project_items(
        client,
        by_project,
        project_ids,
        tasks_by_project,
        dry_run=dry_run,
    )
    logger.info(
        "Vikunja upsert: %s created, %s updated, %s unchanged (dry-run=%s).",
        created,
        updated,
        unchanged,
        dry_run,
    )

    stale_done = 0
    if complete_stale:
        stale_done = _complete_stale_managed_tasks(
            client,
            managed_tasks,
            current_ids,
            dry_run=dry_run,
        )
        if stale_done:
            logger.info("Marked %s stale mirror(s) done.", stale_done)

    logger.info("Sync finished.")
    return 0
