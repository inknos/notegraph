"""GitHub REST API client for fetching issue and PR data."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import requests

from notegraph.schema import Comment, NoteContent, TodoItem

if TYPE_CHECKING:
    from notegraph.schema import GitHubRef

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_COMMENTS_PER_PAGE = 100


def _normalize_newlines(text: str) -> str:
    r"""Replace ``\r\n`` and bare ``\r`` with ``\n``.

    GitHub API responses use Windows-style line endings in text fields
    (body, title, comments). This ensures all output files use Unix
    line endings.

    Args:
        text: Raw string from the API.

    Returns:
        String with only ``\n`` line endings.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


class FetchError(RuntimeError):
    """Raised when a GitHub API request fails."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize with HTTP status code and error message.

        Args:
            status_code: The HTTP status code from the failed request.
            message: Human-readable error detail.
        """
        self.status_code = status_code
        super().__init__(f"GitHub API {status_code}: {message}")


def _build_session(token: str = "") -> requests.Session:
    """Create a configured requests session with GitHub headers.

    Args:
        token: Optional GitHub personal access token.

    Returns:
        A ``requests.Session`` ready to call the GitHub API.
    """
    session = requests.Session()
    session.headers["Accept"] = "application/vnd.github+json"
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def _map_pr_state(state: str, *, merged: bool) -> str:
    """Map a PR's raw state + merged flag to a user-facing status.

    Args:
        state: The ``state`` field from the API (``"open"`` or ``"closed"``).
        merged: Whether the PR has been merged.

    Returns:
        One of ``"open"``, ``"closed"``, or ``"merged"``.
    """
    if state == "closed" and merged:
        return "merged"
    return state


def _fetch_comments(
    session: requests.Session,
    org: str,
    repo: str,
    number: int,
) -> list[Comment]:
    """Fetch all comments for an issue or PR, handling pagination.

    Args:
        session: Authenticated requests session.
        org: Repository owner / organisation.
        repo: Repository name.
        number: Issue or PR number.

    Returns:
        Ordered list of ``Comment`` models.

    Raises:
        FetchError: On any non-2xx response.
    """
    url: str | None = (
        f"{_API_BASE}/repos/{org}/{repo}/issues/{number}/comments?per_page={_COMMENTS_PER_PAGE}"
    )
    comments: list[Comment] = []

    while url:
        resp = session.get(url)
        if not resp.ok:
            raise FetchError(resp.status_code, resp.text)

        comments.extend(
            Comment(
                author=item["user"]["login"],
                date=item["created_at"][:10],
                body=_normalize_newlines(item.get("body") or ""),
            )
            for item in resp.json()
        )

        url = resp.links.get("next", {}).get("url")

    return comments


def fetch(ref: GitHubRef, token: str = "") -> NoteContent:
    """Fetch issue or PR data from the GitHub REST API.

    Args:
        ref: Parsed GitHub reference (org, repo, url_type, number).
        token: Optional GitHub personal access token.

    Returns:
        A populated ``NoteContent`` ready for rendering.

    Raises:
        FetchError: On any non-2xx response.
    """
    session = _build_session(token)

    if ref.url_type == "pull":
        endpoint = f"{_API_BASE}/repos/{ref.org}/{ref.repo}/pulls/{ref.number}"
    else:
        endpoint = f"{_API_BASE}/repos/{ref.org}/{ref.repo}/issues/{ref.number}"

    resp = session.get(endpoint)
    if not resp.ok:
        raise FetchError(resp.status_code, resp.text)

    data = resp.json()

    if ref.url_type == "pull":
        status = _map_pr_state(data["state"], merged=bool(data.get("merged")))
    else:
        status = data["state"]

    comments = _fetch_comments(session, ref.org, ref.repo, ref.number)

    extra: dict[str, str | None] = {}
    if ref.url_type == "pull":
        extra["mergedAt"] = data.get("merged_at")

    return NoteContent(
        title=_normalize_newlines(data["title"]),
        url=data["html_url"],
        source="github",
        status=status,
        author=data["user"]["login"],
        created=data["created_at"][:10],
        description=_normalize_newlines(data.get("body") or ""),
        comments=comments,
        note_type=ref.note_type,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Activity search (--todo)
# ---------------------------------------------------------------------------

_SEARCH_PER_PAGE = 100


def _get_username(session: requests.Session) -> str:
    """Resolve the authenticated GitHub username.

    Args:
        session: Authenticated requests session.

    Returns:
        The login name of the authenticated user.

    Raises:
        FetchError: On any non-2xx response.
    """
    resp = session.get(f"{_API_BASE}/user")
    if not resp.ok:
        raise FetchError(resp.status_code, resp.text)
    return resp.json()["login"]


def _search_items(
    session: requests.Session,
    query: str,
) -> list[dict]:
    """Run a GitHub Search API query, handling pagination.

    Args:
        session: Authenticated requests session.
        query: Full search query string (e.g. ``is:open is:issue involves:user org:foo``).

    Returns:
        List of raw item dicts from the ``items`` array.

    Raises:
        FetchError: On any non-2xx response.
    """
    url: str | None = f"{_API_BASE}/search/issues?per_page={_SEARCH_PER_PAGE}&q={query}"
    items: list[dict] = []

    while url:
        resp = session.get(url)
        if not resp.ok:
            raise FetchError(resp.status_code, resp.text)
        items.extend(resp.json().get("items", []))
        url = resp.links.get("next", {}).get("url")

    return items


_GITHUB_ISSUE_HTML_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<num>\d+)/?$",
)


def _github_timeline_events(
    session: requests.Session,
    owner: str,
    repo: str,
    issue_number: int,
) -> list[dict]:
    """Fetch paginated timeline events for a repository issue."""
    headers = {"Accept": "application/vnd.github+json"}
    url: str | None = (
        f"{_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}/timeline"
        f"?per_page={_SEARCH_PER_PAGE}"
    )
    events: list[dict] = []
    while url:
        resp = session.get(url, headers=headers)
        if not resp.ok:
            raise FetchError(resp.status_code, resp.text)
        batch = resp.json()
        if isinstance(batch, list):
            events.extend(batch)
        url = resp.links.get("next", {}).get("url")
    return events


def _github_latest_assignment_date_iso(
    session: requests.Session,
    owner: str,
    repo: str,
    issue_number: int,
    assignee_login: str,
) -> str | None:
    """Latest ``YYYY-MM-DD`` from an *assigned* event for *assignee_login*, if any."""
    if not assignee_login.strip():
        return None
    latest: str | None = None
    for event in _github_timeline_events(session, owner, repo, issue_number):
        if event.get("event") != "assigned":
            continue
        assignee = event.get("assignee") or {}
        if assignee.get("login") != assignee_login:
            continue
        created = event.get("created_at")
        if created and (latest is None or created > latest):
            latest = created
    return latest[:10] if latest else None


def _apply_github_issue_start_dates(
    session: requests.Session,
    username: str,
    items: list[TodoItem],
) -> list[TodoItem]:
    """Set ``start_date`` on issues via assignment timeline; PRs already use creation date.

    Issues get a ``start_date`` only when an assignment to *username* is found
    in the timeline; otherwise the field stays empty so that unassigned items
    do not receive a spurious due date.
    """
    out: list[TodoItem] = []
    for item in items:
        if item.kind == "pull_request":
            out.append(item)
            continue
        m = _GITHUB_ISSUE_HTML_URL_RE.match(item.url.rstrip("/"))
        assigned: str | None = None
        if m:
            try:
                assigned = _github_latest_assignment_date_iso(
                    session,
                    m["owner"],
                    m["repo"],
                    int(m["num"]),
                    username,
                )
            except FetchError as exc:
                logger.debug(
                    "GitHub timeline %s/%s#%s: %s",
                    m["owner"],
                    m["repo"],
                    m["num"],
                    exc,
                )
        out.append(item.model_copy(update={"start_date": assigned or ""}))
    return out


def _item_to_todo(item: dict) -> TodoItem:
    """Convert a raw GitHub search result item to a ``TodoItem``.

    Args:
        item: A single item dict from the search ``items`` array.

    Returns:
        Populated ``TodoItem``.
    """
    is_pr = "pull_request" in item
    repo_full = item.get("repository_url", "")
    if repo_full:
        repo_full = "/".join(repo_full.rsplit("/", 2)[-2:])

    created_day = (item.get("created_at") or "")[:10]

    return TodoItem(
        url=item["html_url"],
        title=item["title"],
        source="github",
        kind="pull_request" if is_pr else "issue",
        state=item["state"],
        repo=repo_full,
        updated_at=item.get("updated_at", "")[:10],
        created_at=created_day,
        start_date=created_day if is_pr else "",
    )


def fetch_todo(
    *,
    orgs: list[str] | None = None,
    repos: list[str] | None = None,
    token: str = "",
) -> list[TodoItem]:
    """Search GitHub for open issues/PRs the user is involved in.

    Mirrors the logic of ``todo-page.sh``: for each org/repo scope,
    queries for issues+involves, PRs+involves, and PRs+review-requested.
    Results are deduplicated by URL and sorted by ``updated_at`` descending.
    Open **issues** trigger one extra timeline API request each to resolve the
    latest **assignment** date for the authenticated user (pull requests use
    creation date only).

    Args:
        orgs: GitHub organisations to search (``--owner`` scope).
        repos: Specific ``owner/repo`` pairs to search.
        token: GitHub personal access token (recommended for search).

    Returns:
        Deduplicated, sorted list of ``TodoItem`` objects.

    Raises:
        FetchError: On any API failure.
        ValueError: If neither *orgs* nor *repos* is provided.
    """
    if not orgs and not repos:
        msg = "At least one org or repo is required for --todo."
        raise ValueError(msg)

    session = _build_session(token)
    username = _get_username(session)
    logger.info("GitHub user: %s", username)

    raw_items: list[dict] = []

    for org in orgs or []:
        raw_items.extend(
            _search_items(session, f"is:open is:issue involves:{username} org:{org}"),
        )
        raw_items.extend(
            _search_items(session, f"is:open is:pr involves:{username} org:{org}"),
        )
        raw_items.extend(
            _search_items(
                session,
                f"is:open is:pr review-requested:{username} org:{org}",
            ),
        )

    for repo in repos or []:
        raw_items.extend(
            _search_items(session, f"is:open is:issue involves:{username} repo:{repo}"),
        )
        raw_items.extend(
            _search_items(session, f"is:open is:pr involves:{username} repo:{repo}"),
        )
        raw_items.extend(
            _search_items(
                session,
                f"is:open is:pr review-requested:{username} repo:{repo}",
            ),
        )

    seen: set[str] = set()
    deduped: list[TodoItem] = []
    for item in raw_items:
        url = item["html_url"]
        if url not in seen:
            seen.add(url)
            deduped.append(_item_to_todo(item))

    deduped.sort(key=lambda t: t.updated_at, reverse=True)
    return _apply_github_issue_start_dates(session, username, deduped)


def fetch_todo_search(*, query: str, token: str = "") -> list[TodoItem]:
    """Search GitHub issues/PRs with a single ``q`` string (paginated).

    Uses the same REST helpers as :func:`fetch_todo`. Intended for callers
    that need one global query (e.g. ``notegraph todo --vikunja``) instead of per-org/repo
    scopes.

    Args:
        query: Raw GitHub issue search query (must be non-empty after strip).
        token: GitHub personal access token.

    Returns:
        Deduplicated results sorted by ``updated_at`` descending. Empty *query*
        yields an empty list without calling the API.
        Issues include assignment-derived ``start_date`` (see :func:`fetch_todo`).

    Raises:
        FetchError: On any non-2xx response.
    """
    q = query.strip()
    if not q:
        return []

    session = _build_session(token)
    username = _get_username(session)
    logger.info("GitHub user: %s", username)
    raw_items = _search_items(session, q)

    seen: set[str] = set()
    deduped: list[TodoItem] = []
    for item in raw_items:
        url = item["html_url"]
        if url not in seen:
            seen.add(url)
            deduped.append(_item_to_todo(item))

    deduped.sort(key=lambda t: t.updated_at, reverse=True)
    return _apply_github_issue_start_dates(session, username, deduped)
