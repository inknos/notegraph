"""Jira Cloud REST API v3 client for fetching issue data."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import requests
from atlas_doc_parser.api import NodeDoc

from notegraph.schema import Comment, NoteContent, TodoItem

if TYPE_CHECKING:
    from notegraph.schema import JiraRef

logger = logging.getLogger(__name__)

_API_VERSION = "3"
_GH_URL_RE = re.compile(r"https?://github\.com/[^/]+/[^/]+/(?:pull|issues)/\d+")
_WIKI_LINK_RE = re.compile(r"^\[([^|\]]+)")


class FetchError(RuntimeError):
    """Raised when a Jira API request fails."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize with HTTP status code and error message.

        Args:
            status_code: The HTTP status code from the failed request.
            message: Human-readable error detail.
        """
        self.status_code = status_code
        super().__init__(f"Jira API {status_code}: {message}")


def _build_session(email: str = "", token: str = "") -> requests.Session:
    """Create a configured requests session with Jira headers.

    Uses HTTP Basic auth with the Jira account email and an API token,
    which is the standard authentication method for Jira Cloud.

    Args:
        email: Jira account email.
        token: Jira API token.

    Returns:
        A ``requests.Session`` ready to call the Jira API.
    """
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    if email and token:
        session.auth = (email, token)
    return session


def _adf_to_markdown(adf: dict | None) -> str:
    """Convert an Atlassian Document Format JSON object to markdown.

    Args:
        adf: ADF JSON dict (the ``description`` or comment ``body``
             from the Jira v3 API).  May be ``None`` for empty fields.

    Returns:
        Markdown string, or ``""`` if *adf* is falsy or unparseable.
    """
    if not adf:
        return ""
    try:
        doc = NodeDoc.from_dict(adf)
        return doc.to_markdown().strip()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to parse ADF document, returning empty string")
        return ""


def _extract_github_url(raw: str | dict | None) -> str | None:
    """Extract a GitHub PR/issue URL from a Jira custom field value.

    The custom field can appear in several formats:

    - Plain URL string: ``https://github.com/org/repo/pull/123``
    - Jira wiki markup: ``[url|url|smart-link]``
    - ADF JSON dict (rich text field)

    Args:
        raw: The raw value of the custom field.

    Returns:
        The first GitHub URL found, or ``None``.
    """
    if raw is None:
        return None

    if isinstance(raw, dict):
        text = _adf_to_markdown(raw)
    else:
        text = str(raw)
        wiki_match = _WIKI_LINK_RE.match(text)
        if wiki_match:
            text = wiki_match.group(1).strip()

    match = _GH_URL_RE.search(text)
    return match.group(0) if match else None


def _extract_comments(fields: dict) -> list[Comment]:
    """Extract comments from issue fields.

    Args:
        fields: The ``fields`` dict from the Jira API response.

    Returns:
        Ordered list of ``Comment`` models.
    """
    comment_data = fields.get("comment", {})
    if not isinstance(comment_data, dict):
        return []
    raw_comments = comment_data.get("comments", [])
    return [
        Comment(
            author=(c.get("author") or {}).get("displayName", "Unknown"),
            date=(c.get("created") or "")[:10],
            body=_adf_to_markdown(c.get("body")),
        )
        for c in raw_comments
    ]


def fetch(
    ref: JiraRef,
    *,
    email: str = "",
    token: str = "",
    github_field: str = "customfield_10875",
) -> NoteContent:
    """Fetch issue data from the Jira Cloud REST API v3.

    Args:
        ref: Parsed Jira reference (endpoint and key).
        email: Jira account email for basic auth.
        token: Jira API token.
        github_field: Custom field ID that may contain a linked GitHub
            PR/issue URL.

    Returns:
        A populated ``NoteContent`` ready for rendering.

    Raises:
        FetchError: On any non-2xx response.
    """
    session = _build_session(email, token)
    url = f"https://{ref.endpoint}/rest/api/{_API_VERSION}/issue/{ref.key}"
    requested_fields = (
        f"summary,status,assignee,description,created,issuetype,comment,{github_field}"
    )

    resp = session.get(url, params={"fields": requested_fields})
    if not resp.ok:
        raise FetchError(resp.status_code, resp.text)

    data = resp.json()
    fields = data["fields"]

    assignee_obj = fields.get("assignee")
    assignee_name = assignee_obj["displayName"] if assignee_obj else "Unassigned"

    issue_type_obj = fields.get("issuetype") or {}
    issue_type = issue_type_obj.get("name", "issue")

    gh_url = _extract_github_url(fields.get(github_field))

    extra: dict[str, str | None] = {
        "assignee": assignee_name,
        "issue_type": issue_type,
    }
    if gh_url:
        extra["github_url"] = gh_url

    return NoteContent(
        title=fields.get("summary", ""),
        url=ref.browse_url,
        source="jira",
        status=(fields.get("status") or {}).get("name", "Unknown"),
        author=assignee_name,
        created=(fields.get("created") or "")[:10],
        description=_adf_to_markdown(fields.get("description")),
        comments=_extract_comments(fields),
        note_type=issue_type.lower(),
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Activity search (--todo)
# ---------------------------------------------------------------------------

_SEARCH_MAX_RESULTS = 100


def _item_to_todo(issue: dict, endpoint: str) -> TodoItem:
    """Convert a raw Jira search result item to a ``TodoItem``.

    Args:
        issue: A single issue dict from the search ``issues`` array.
        endpoint: Jira instance hostname (for building the browse URL).

    Returns:
        Populated ``TodoItem``.
    """
    fields = issue.get("fields", {})
    issue_type = (fields.get("issuetype") or {}).get("name", "issue")
    project_key = (fields.get("project") or {}).get("key", "")

    return TodoItem(
        url=f"https://{endpoint}/browse/{issue['key']}",
        title=fields.get("summary", ""),
        source="jira",
        kind=issue_type.lower(),
        state=(fields.get("status") or {}).get("name", "Unknown"),
        repo=project_key,
        updated_at=(fields.get("updated") or "")[:10],
    )


def fetch_todo(
    *,
    endpoint: str,
    jql: str = "",
    email: str = "",
    token: str = "",
) -> list[TodoItem]:
    """Search Jira for issues matching a JQL query.

    Uses ``POST /rest/api/3/search/jql`` with ``nextPageToken``
    pagination.  If *jql* is empty, returns an empty list immediately
    without making any API calls.

    Args:
        endpoint: Jira instance hostname (e.g. ``redhat.atlassian.net``).
        jql: JQL query string.  Empty string means "no search".
        email: Jira account email for basic auth.
        token: Jira API token.

    Returns:
        List of ``TodoItem`` objects sorted by ``updated_at`` descending.

    Raises:
        FetchError: On any non-2xx response.
    """
    if not jql:
        return []

    session = _build_session(email, token)

    if not (email and token):
        logger.warning("No Jira credentials configured — results may be empty")

    url = f"https://{endpoint}/rest/api/{_API_VERSION}/search/jql"

    items: list[TodoItem] = []
    next_token: str | None = None

    while True:
        body: dict[str, str | int | list[str]] = {
            "jql": jql,
            "fields": ["summary", "status", "issuetype", "updated", "project"],
            "maxResults": _SEARCH_MAX_RESULTS,
        }
        if next_token is not None:
            body["nextPageToken"] = next_token

        resp = session.post(url, json=body)
        if not resp.ok:
            raise FetchError(resp.status_code, resp.text)

        data = resp.json()
        items.extend(_item_to_todo(issue, endpoint) for issue in data.get("issues", []))

        next_token = data.get("nextPageToken")
        if not next_token:
            break

    items.sort(key=lambda t: t.updated_at, reverse=True)
    return items
