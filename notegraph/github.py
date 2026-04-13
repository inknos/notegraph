"""GitHub REST API client for fetching issue and PR data."""

from __future__ import annotations

import logging
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

    return TodoItem(
        url=item["html_url"],
        title=item["title"],
        source="github",
        kind="pull_request" if is_pr else "issue",
        state=item["state"],
        repo=repo_full,
        updated_at=item.get("updated_at", "")[:10],
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
    return deduped
