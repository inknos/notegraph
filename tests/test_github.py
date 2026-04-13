"""Tests for the GitHub REST API fetcher."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from notegraph import writer
from notegraph.github import (
    FetchError,
    _build_session,
    _item_to_todo,
    _map_pr_state,
    _normalize_newlines,
    fetch,
    fetch_todo,
)
from notegraph.schema import GitHubRef

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PR_JSON: dict[str, Any] = {
    "title": "Fix container networking regression",
    "html_url": "https://github.com/containers/podman/pull/24126",
    "state": "open",
    "merged": False,
    "merged_at": None,
    "user": {"login": "developer"},
    "created_at": "2024-03-15T10:00:00Z",
    "body": "This PR fixes the networking regression.",
}

_PR_MERGED_JSON: dict[str, Any] = {
    **_PR_JSON,
    "state": "closed",
    "merged": True,
    "merged_at": "2024-03-20T12:00:00Z",
}

_ISSUE_JSON: dict[str, Any] = {
    "title": "Networking broken after upgrade",
    "html_url": "https://github.com/containers/podman/issues/999",
    "state": "open",
    "user": {"login": "reporter"},
    "created_at": "2024-04-01T08:30:00Z",
    "body": "After upgrading to v5, networking is broken.",
}

_COMMENTS_PAGE_1: list[dict[str, Any]] = [
    {
        "user": {"login": "reviewer1"},
        "created_at": "2024-03-16T09:00:00Z",
        "body": "LGTM, minor nit.",
    },
    {
        "user": {"login": "reviewer2"},
        "created_at": "2024-03-17T11:00:00Z",
        "body": "Needs rebase.",
    },
]

_COMMENTS_PAGE_2: list[dict[str, Any]] = [
    {
        "user": {"login": "maintainer"},
        "created_at": "2024-03-18T15:00:00Z",
        "body": "Merged, thanks!",
    },
]


@pytest.fixture
def pr_ref() -> GitHubRef:
    return GitHubRef(org="containers", repo="podman", url_type="pull", number=24126)


@pytest.fixture
def issue_ref() -> GitHubRef:
    return GitHubRef(org="containers", repo="podman", url_type="issues", number=999)


def _mock_response(
    json_data: Any,
    *,
    ok: bool = True,
    status_code: int = 200,
    links: dict | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = "" if ok else "Not Found"
    resp.links = links or {}
    return resp


# ---------------------------------------------------------------------------
# _build_session
# ---------------------------------------------------------------------------


class TestBuildSession:
    def test_accept_header(self):
        session = _build_session()
        assert session.headers["Accept"] == "application/vnd.github+json"

    def test_auth_header_when_token(self):
        session = _build_session("ghp_abc123")
        assert session.headers["Authorization"] == "Bearer ghp_abc123"

    def test_no_auth_header_without_token(self):
        session = _build_session()
        assert "Authorization" not in session.headers

    def test_empty_token_no_auth(self):
        session = _build_session("")
        assert "Authorization" not in session.headers


# ---------------------------------------------------------------------------
# _map_pr_state
# ---------------------------------------------------------------------------


class TestMapPrState:
    def test_open(self):
        assert _map_pr_state("open", merged=False) == "open"

    def test_closed_not_merged(self):
        assert _map_pr_state("closed", merged=False) == "closed"

    def test_closed_merged(self):
        assert _map_pr_state("closed", merged=True) == "merged"


# ---------------------------------------------------------------------------
# fetch — PR
# ---------------------------------------------------------------------------


class TestFetchPR:
    @patch("notegraph.github._build_session")
    def test_open_pr(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session

        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response([]),
        ]

        content = fetch(pr_ref, token="tok")
        assert content.title == "Fix container networking regression"
        assert content.source == "github"
        assert content.status == "open"
        assert content.author == "developer"
        assert content.created == "2024-03-15"
        assert content.note_type == "pull_request"
        assert content.extra.get("mergedAt") is None

    @patch("notegraph.github._build_session")
    def test_merged_pr(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session

        session.get.side_effect = [
            _mock_response(_PR_MERGED_JSON),
            _mock_response([]),
        ]

        content = fetch(pr_ref)
        assert content.status == "merged"
        assert content.extra["mergedAt"] == "2024-03-20T12:00:00Z"

    @patch("notegraph.github._build_session")
    def test_pr_with_comments(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session

        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response(_COMMENTS_PAGE_1),
        ]

        content = fetch(pr_ref)
        assert len(content.comments) == 2
        assert content.comments[0].author == "reviewer1"
        assert content.comments[0].date == "2024-03-16"
        assert content.comments[1].body == "Needs rebase."

    @patch("notegraph.github._build_session")
    def test_pr_endpoint_url(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response([]),
        ]

        fetch(pr_ref)

        first_call_url = session.get.call_args_list[0][0][0]
        assert "/repos/containers/podman/pulls/24126" in first_call_url

    @patch("notegraph.github._build_session")
    def test_null_body_becomes_empty(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        json_data = {**_PR_JSON, "body": None}
        session.get.side_effect = [
            _mock_response(json_data),
            _mock_response([]),
        ]

        content = fetch(pr_ref)
        assert content.description == ""


# ---------------------------------------------------------------------------
# fetch — Issue
# ---------------------------------------------------------------------------


class TestFetchIssue:
    @patch("notegraph.github._build_session")
    def test_open_issue(self, mock_build, issue_ref):
        session = MagicMock()
        mock_build.return_value = session

        session.get.side_effect = [
            _mock_response(_ISSUE_JSON),
            _mock_response([]),
        ]

        content = fetch(issue_ref)
        assert content.title == "Networking broken after upgrade"
        assert content.source == "github"
        assert content.status == "open"
        assert content.author == "reporter"
        assert content.note_type == "issue"
        assert content.extra == {}

    @patch("notegraph.github._build_session")
    def test_issue_endpoint_url(self, mock_build, issue_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            _mock_response(_ISSUE_JSON),
            _mock_response([]),
        ]

        fetch(issue_ref)

        first_call_url = session.get.call_args_list[0][0][0]
        assert "/repos/containers/podman/issues/999" in first_call_url


# ---------------------------------------------------------------------------
# Comment pagination
# ---------------------------------------------------------------------------


class TestCommentPagination:
    @patch("notegraph.github._build_session")
    def test_two_pages(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session

        page2_url = "https://api.github.com/repos/containers/podman/issues/24126/comments?page=2"
        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response(
                _COMMENTS_PAGE_1,
                links={"next": {"url": page2_url}},
            ),
            _mock_response(_COMMENTS_PAGE_2),
        ]

        content = fetch(pr_ref)
        assert len(content.comments) == 3
        assert content.comments[2].author == "maintainer"
        assert content.comments[2].body == "Merged, thanks!"

    @patch("notegraph.github._build_session")
    def test_no_comments(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response([]),
        ]

        content = fetch(pr_ref)
        assert content.comments == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    @patch("notegraph.github._build_session")
    def test_main_request_404(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(
            None,
            ok=False,
            status_code=404,
        )

        with pytest.raises(FetchError, match="404"):
            fetch(pr_ref)

    @patch("notegraph.github._build_session")
    def test_comments_request_403(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response(None, ok=False, status_code=403),
        ]

        with pytest.raises(FetchError, match="403"):
            fetch(pr_ref)

    def test_fetch_error_attributes(self):
        err = FetchError(422, "Validation failed")
        assert err.status_code == 422
        assert "422" in str(err)
        assert "Validation failed" in str(err)


# ---------------------------------------------------------------------------
# Auth forwarding
# ---------------------------------------------------------------------------


class TestAuth:
    @patch("notegraph.github._build_session")
    def test_token_forwarded(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response([]),
        ]

        fetch(pr_ref, token="my-token")
        mock_build.assert_called_once_with("my-token")

    @patch("notegraph.github._build_session")
    def test_no_token(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response([]),
        ]

        fetch(pr_ref)
        mock_build.assert_called_once_with("")


# ---------------------------------------------------------------------------
# Newline normalization
# ---------------------------------------------------------------------------


class TestNormalizeNewlines:
    def test_crlf_replaced(self):
        assert _normalize_newlines("a\r\nb") == "a\nb"

    def test_bare_cr_replaced(self):
        assert _normalize_newlines("a\rb") == "a\nb"

    def test_lf_unchanged(self):
        assert _normalize_newlines("a\nb") == "a\nb"

    def test_mixed_endings(self):
        assert _normalize_newlines("a\r\nb\rc\nd") == "a\nb\nc\nd"

    def test_empty_string(self):
        assert _normalize_newlines("") == ""

    def test_no_newlines(self):
        assert _normalize_newlines("hello") == "hello"


class TestFetchStripsCarriageReturns:
    @patch("notegraph.github._build_session")
    def test_title_stripped(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        json_data = {**_PR_JSON, "title": "Fix\r\nnetworking"}
        session.get.side_effect = [
            _mock_response(json_data),
            _mock_response([]),
        ]

        content = fetch(pr_ref)
        assert "\r" not in content.title
        assert content.title == "Fix\nnetworking"

    @patch("notegraph.github._build_session")
    def test_description_stripped(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        json_data = {**_PR_JSON, "body": "Line 1\r\nLine 2\r\n\r\nLine 3"}
        session.get.side_effect = [
            _mock_response(json_data),
            _mock_response([]),
        ]

        content = fetch(pr_ref)
        assert "\r" not in content.description
        assert content.description == "Line 1\nLine 2\n\nLine 3"

    @patch("notegraph.github._build_session")
    def test_comment_body_stripped(self, mock_build, pr_ref):
        session = MagicMock()
        mock_build.return_value = session
        comments_json = [
            {
                "user": {"login": "user1"},
                "created_at": "2024-01-01T00:00:00Z",
                "body": "Nice\r\nwork!",
            },
        ]
        session.get.side_effect = [
            _mock_response(_PR_JSON),
            _mock_response(comments_json),
        ]

        content = fetch(pr_ref)
        assert "\r" not in content.comments[0].body
        assert content.comments[0].body == "Nice\nwork!"

    @patch("notegraph.github._build_session")
    def test_no_cr_in_written_files(self, mock_build, pr_ref, tmp_path):
        r"""End-to-end: fetched data with \r\n produces files without \r."""
        session = MagicMock()
        mock_build.return_value = session
        json_data = {
            **_PR_JSON,
            "title": "Title\r\nwrap",
            "body": "Paragraph 1\r\n\r\nParagraph 2\r\n",
        }
        comments_json = [
            {
                "user": {"login": "rev"},
                "created_at": "2024-01-01T00:00:00Z",
                "body": "Comment\r\nwith\r\nCRLF",
            },
        ]
        session.get.side_effect = [
            _mock_response(json_data),
            _mock_response(comments_json),
        ]

        content = fetch(pr_ref)
        dest = str(tmp_path / "out")
        writer.write(content, pr_ref, dest, "logseq")

        for path in tmp_path.rglob("*.md"):
            raw = path.read_bytes()
            assert b"\r" not in raw, f"{path.name} contains \\r"


# ---------------------------------------------------------------------------
# _item_to_todo
# ---------------------------------------------------------------------------

_SEARCH_ISSUE: dict[str, Any] = {
    "html_url": "https://github.com/containers/podman/issues/100",
    "title": "Bug in networking",
    "state": "open",
    "updated_at": "2026-04-10T12:00:00Z",
    "repository_url": "https://api.github.com/repos/containers/podman",
}

_SEARCH_PR: dict[str, Any] = {
    "html_url": "https://github.com/containers/podman/pull/200",
    "title": "Fix networking",
    "state": "open",
    "updated_at": "2026-04-12T08:00:00Z",
    "repository_url": "https://api.github.com/repos/containers/podman",
    "pull_request": {"url": "..."},
}

_SEARCH_PR_OTHER: dict[str, Any] = {
    "html_url": "https://github.com/containers/buildah/pull/50",
    "title": "Refactor layers",
    "state": "open",
    "updated_at": "2026-04-11T06:00:00Z",
    "repository_url": "https://api.github.com/repos/containers/buildah",
    "pull_request": {"url": "..."},
}


class TestItemToTodo:
    def test_issue_kind(self):
        item = _item_to_todo(_SEARCH_ISSUE)
        assert item.kind == "issue"
        assert item.source == "github"

    def test_pr_kind(self):
        item = _item_to_todo(_SEARCH_PR)
        assert item.kind == "pull_request"

    def test_repo_extracted(self):
        item = _item_to_todo(_SEARCH_PR)
        assert item.repo == "containers/podman"

    def test_updated_at_date_only(self):
        item = _item_to_todo(_SEARCH_PR)
        assert item.updated_at == "2026-04-12"

    def test_url_preserved(self):
        item = _item_to_todo(_SEARCH_ISSUE)
        assert item.url == _SEARCH_ISSUE["html_url"]


# ---------------------------------------------------------------------------
# fetch_todo
# ---------------------------------------------------------------------------


class TestFetchTodo:
    def _user_resp(self) -> MagicMock:
        return _mock_response({"login": "testuser"})

    def _search_resp(self, items: list[dict]) -> MagicMock:
        return _mock_response({"items": items})

    @patch("notegraph.github._build_session")
    def test_basic_org_search(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            self._user_resp(),
            self._search_resp([_SEARCH_ISSUE]),
            self._search_resp([_SEARCH_PR]),
            self._search_resp([]),
        ]

        items = fetch_todo(orgs=["containers"])
        assert len(items) == 2
        urls = {i.url for i in items}
        assert _SEARCH_ISSUE["html_url"] in urls
        assert _SEARCH_PR["html_url"] in urls

    @patch("notegraph.github._build_session")
    def test_dedup(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            self._user_resp(),
            self._search_resp([_SEARCH_PR]),
            self._search_resp([_SEARCH_PR]),
            self._search_resp([_SEARCH_PR]),
        ]

        items = fetch_todo(orgs=["containers"])
        assert len(items) == 1

    @patch("notegraph.github._build_session")
    def test_sorted_by_updated_at_desc(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            self._user_resp(),
            self._search_resp([_SEARCH_ISSUE, _SEARCH_PR_OTHER]),
            self._search_resp([_SEARCH_PR]),
            self._search_resp([]),
        ]

        items = fetch_todo(orgs=["containers"])
        dates = [i.updated_at for i in items]
        assert dates == sorted(dates, reverse=True)

    @patch("notegraph.github._build_session")
    def test_repo_scope(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            self._user_resp(),
            self._search_resp([_SEARCH_ISSUE]),
            self._search_resp([]),
            self._search_resp([]),
        ]

        items = fetch_todo(repos=["containers/podman"])
        assert len(items) == 1
        assert items[0].repo == "containers/podman"

    @patch("notegraph.github._build_session")
    def test_combined_org_and_repo(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            self._user_resp(),
            self._search_resp([_SEARCH_ISSUE]),
            self._search_resp([]),
            self._search_resp([]),
            self._search_resp([_SEARCH_PR_OTHER]),
            self._search_resp([]),
            self._search_resp([]),
        ]

        items = fetch_todo(orgs=["containers"], repos=["containers/buildah"])
        assert len(items) == 2

    def test_no_scope_raises(self):
        with pytest.raises(ValueError, match="At least one org or repo"):
            fetch_todo()

    @patch("notegraph.github._build_session")
    def test_empty_results(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.get.side_effect = [
            self._user_resp(),
            self._search_resp([]),
            self._search_resp([]),
            self._search_resp([]),
        ]

        items = fetch_todo(orgs=["emptyorg"])
        assert items == []

    @patch("notegraph.github._build_session")
    def test_user_api_error(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(
            {}, ok=False, status_code=401,
        )

        with pytest.raises(FetchError):
            fetch_todo(orgs=["containers"])
