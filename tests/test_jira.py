"""Tests for the Jira REST API fetcher."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from notegraph.jira import (
    FetchError,
    _adf_to_markdown,
    _build_session,
    _extract_comments,
    _extract_github_url,
    _item_to_todo,
    fetch,
    fetch_todo,
)
from notegraph.schema import JiraRef

# ---------------------------------------------------------------------------
# ADF fixtures
# ---------------------------------------------------------------------------

_ADF_SIMPLE: dict[str, Any] = {
    "version": 1,
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Add retry logic to API calls."}],
        },
    ],
}

_ADF_MULTILINE: dict[str, Any] = {
    "version": 1,
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "First paragraph."}],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Second paragraph."}],
        },
    ],
}

_ADF_COMMENT: dict[str, Any] = {
    "version": 1,
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Priority raised to high."}],
        },
    ],
}

# ---------------------------------------------------------------------------
# Issue JSON fixture
# ---------------------------------------------------------------------------

_ISSUE_JSON: dict[str, Any] = {
    "fields": {
        "summary": "Implement retry logic for API calls",
        "status": {"name": "In Progress"},
        "assignee": {"displayName": "Ada Lovelace"},
        "description": _ADF_SIMPLE,
        "created": "2024-01-10T09:15:00.000+0000",
        "issuetype": {"name": "Story"},
        "comment": {
            "comments": [
                {
                    "author": {"displayName": "PM User"},
                    "created": "2024-01-12T14:30:00.000+0000",
                    "body": _ADF_COMMENT,
                },
            ],
        },
        "customfield_10875": "https://github.com/acme/widgets/pull/123",
    },
}

_ISSUE_NO_ASSIGNEE_JSON: dict[str, Any] = {
    "fields": {
        **_ISSUE_JSON["fields"],
        "assignee": None,
    },
}

_ISSUE_NO_DESC_JSON: dict[str, Any] = {
    "fields": {
        **_ISSUE_JSON["fields"],
        "description": None,
    },
}

_ISSUE_NO_GH_JSON: dict[str, Any] = {
    "fields": {
        **_ISSUE_JSON["fields"],
        "customfield_10875": None,
    },
}


@pytest.fixture
def jira_ref() -> JiraRef:
    return JiraRef(endpoint="test.atlassian.net", key="RUN-3555")


def _mock_response(
    json_data: Any,
    *,
    ok: bool = True,
    status_code: int = 200,
) -> MagicMock:
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = "" if ok else "Not Found"
    return resp


# ---------------------------------------------------------------------------
# _build_session
# ---------------------------------------------------------------------------


class TestBuildSession:
    def test_accept_header(self):
        session = _build_session()
        assert session.headers["Accept"] == "application/json"

    def test_basic_auth_when_credentials(self):
        session = _build_session("user@example.com", "token123")
        assert session.auth == ("user@example.com", "token123")

    def test_no_auth_without_credentials(self):
        session = _build_session()
        assert session.auth is None

    def test_no_auth_with_empty_strings(self):
        session = _build_session("", "")
        assert session.auth is None

    def test_no_auth_with_partial_credentials(self):
        session = _build_session("user@example.com", "")
        assert session.auth is None


# ---------------------------------------------------------------------------
# _adf_to_markdown
# ---------------------------------------------------------------------------


class TestAdfToMarkdown:
    def test_simple_paragraph(self):
        result = _adf_to_markdown(_ADF_SIMPLE)
        assert "Add retry logic to API calls." in result

    def test_multiline(self):
        result = _adf_to_markdown(_ADF_MULTILINE)
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_none_returns_empty(self):
        assert _adf_to_markdown(None) == ""

    def test_empty_dict_returns_empty(self):
        assert _adf_to_markdown({}) == ""

    def test_malformed_returns_empty(self):
        assert _adf_to_markdown({"type": "garbage", "version": 99}) == ""

    def test_result_is_stripped(self):
        result = _adf_to_markdown(_ADF_SIMPLE)
        assert result == result.strip()


# ---------------------------------------------------------------------------
# _extract_github_url
# ---------------------------------------------------------------------------


class TestExtractGithubUrl:
    def test_plain_url(self):
        url = "https://github.com/acme/widgets/pull/123"
        assert _extract_github_url(url) == url

    def test_issues_url(self):
        url = "https://github.com/acme/widgets/issues/456"
        assert _extract_github_url(url) == url

    def test_wiki_markup(self):
        raw = "[https://github.com/acme/widgets/pull/123|https://github.com/acme/widgets/pull/123|smart-link]"
        assert _extract_github_url(raw) == "https://github.com/acme/widgets/pull/123"

    def test_none_returns_none(self):
        assert _extract_github_url(None) is None

    def test_empty_string_returns_none(self):
        assert _extract_github_url("") is None

    def test_no_match_returns_none(self):
        assert _extract_github_url("https://gitlab.com/org/repo/merge_requests/1") is None

    def test_adf_with_url(self):
        adf = {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "See https://github.com/org/repo/pull/99"},
                    ],
                },
            ],
        }
        assert _extract_github_url(adf) == "https://github.com/org/repo/pull/99"

    def test_random_string_no_match(self):
        assert _extract_github_url("just some text") is None


# ---------------------------------------------------------------------------
# _extract_comments
# ---------------------------------------------------------------------------


class TestExtractComments:
    def test_basic_comments(self):
        fields = _ISSUE_JSON["fields"]
        comments = _extract_comments(fields)
        assert len(comments) == 1
        assert comments[0].author == "PM User"
        assert comments[0].date == "2024-01-12"
        assert "Priority raised to high." in comments[0].body

    def test_no_comments_field(self):
        assert _extract_comments({}) == []

    def test_empty_comments_array(self):
        fields = {"comment": {"comments": []}}
        assert _extract_comments(fields) == []

    def test_missing_author(self):
        fields = {
            "comment": {
                "comments": [
                    {"created": "2024-01-01T00:00:00Z", "body": _ADF_SIMPLE},
                ],
            },
        }
        comments = _extract_comments(fields)
        assert comments[0].author == "Unknown"


# ---------------------------------------------------------------------------
# fetch — basic issue
# ---------------------------------------------------------------------------


class TestFetchIssue:
    @patch("notegraph.jira._build_session")
    def test_basic_issue(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_JSON)

        content = fetch(jira_ref, email="a@b.com", token="tok")
        assert content.title == "Implement retry logic for API calls"
        assert content.source == "jira"
        assert content.status == "In Progress"
        assert content.author == "Ada Lovelace"
        assert content.created == "2024-01-10"
        assert content.note_type == "story"
        assert "Add retry logic" in content.description

    @patch("notegraph.jira._build_session")
    def test_null_assignee(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_NO_ASSIGNEE_JSON)

        content = fetch(jira_ref)
        assert content.author == "Unassigned"
        assert content.extra["assignee"] == "Unassigned"

    @patch("notegraph.jira._build_session")
    def test_null_description(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_NO_DESC_JSON)

        content = fetch(jira_ref)
        assert content.description == ""

    @patch("notegraph.jira._build_session")
    def test_browse_url(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_JSON)

        content = fetch(jira_ref)
        assert content.url == "https://test.atlassian.net/browse/RUN-3555"

    @patch("notegraph.jira._build_session")
    def test_comments_extracted(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_JSON)

        content = fetch(jira_ref)
        assert len(content.comments) == 1
        assert content.comments[0].author == "PM User"
        assert "Priority raised" in content.comments[0].body

    @patch("notegraph.jira._build_session")
    def test_issue_type_in_extra(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_JSON)

        content = fetch(jira_ref)
        assert content.extra["issue_type"] == "Story"
        assert content.note_type == "story"

    @patch("notegraph.jira._build_session")
    def test_github_url_in_extra(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_JSON)

        content = fetch(jira_ref)
        assert content.extra["github_url"] == "https://github.com/acme/widgets/pull/123"

    @patch("notegraph.jira._build_session")
    def test_no_github_url(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_NO_GH_JSON)

        content = fetch(jira_ref)
        assert "github_url" not in content.extra

    @patch("notegraph.jira._build_session")
    def test_endpoint_url(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_JSON)

        fetch(jira_ref)

        call_url = session.get.call_args[0][0]
        assert "/rest/api/3/issue/RUN-3555" in call_url
        assert "test.atlassian.net" in call_url

    @patch("notegraph.jira._build_session")
    def test_custom_github_field(self, mock_build, jira_ref):
        custom_json = {
            "fields": {
                **_ISSUE_JSON["fields"],
                "customfield_99999": "https://github.com/org/repo/issues/1",
            },
        }
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(custom_json)

        content = fetch(jira_ref, github_field="customfield_99999")
        assert content.extra["github_url"] == "https://github.com/org/repo/issues/1"

        params = session.get.call_args[1]["params"]
        assert "customfield_99999" in params["fields"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    @patch("notegraph.jira._build_session")
    def test_404(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(None, ok=False, status_code=404)

        with pytest.raises(FetchError, match="404"):
            fetch(jira_ref)

    @patch("notegraph.jira._build_session")
    def test_401(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(None, ok=False, status_code=401)

        with pytest.raises(FetchError, match="401"):
            fetch(jira_ref)

    def test_fetch_error_attributes(self):
        err = FetchError(422, "Validation failed")
        assert err.status_code == 422
        assert "422" in str(err)
        assert "Validation failed" in str(err)


# ---------------------------------------------------------------------------
# Auth forwarding
# ---------------------------------------------------------------------------


class TestAuth:
    @patch("notegraph.jira._build_session")
    def test_credentials_forwarded(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_JSON)

        fetch(jira_ref, email="a@b.com", token="tok")
        mock_build.assert_called_once_with("a@b.com", "tok")

    @patch("notegraph.jira._build_session")
    def test_no_credentials(self, mock_build, jira_ref):
        session = MagicMock()
        mock_build.return_value = session
        session.get.return_value = _mock_response(_ISSUE_JSON)

        fetch(jira_ref)
        mock_build.assert_called_once_with("", "")


# ---------------------------------------------------------------------------
# _item_to_todo
# ---------------------------------------------------------------------------

_SEARCH_ISSUE: dict[str, Any] = {
    "key": "RUN-100",
    "fields": {
        "summary": "Fix the widget",
        "status": {"name": "In Progress"},
        "issuetype": {"name": "Bug"},
        "project": {"key": "RUN"},
        "updated": "2026-04-10T12:00:00.000+0000",
    },
}


class TestItemToTodo:
    def test_basic_conversion(self):
        item = _item_to_todo(_SEARCH_ISSUE, "redhat.atlassian.net")
        assert item.url == "https://redhat.atlassian.net/browse/RUN-100"
        assert item.title == "Fix the widget"
        assert item.source == "jira"
        assert item.kind == "bug"
        assert item.state == "In Progress"
        assert item.repo == "RUN"
        assert item.updated_at == "2026-04-10"

    def test_missing_fields_defaults(self):
        issue: dict[str, Any] = {"key": "X-1", "fields": {}}
        item = _item_to_todo(issue, "jira.example.com")
        assert item.url == "https://jira.example.com/browse/X-1"
        assert item.title == ""
        assert item.kind == "issue"
        assert item.state == "Unknown"
        assert item.repo == ""
        assert item.updated_at == ""

    def test_no_fields_key(self):
        issue: dict[str, Any] = {"key": "Y-2"}
        item = _item_to_todo(issue, "example.net")
        assert item.title == ""


# ---------------------------------------------------------------------------
# fetch_todo
# ---------------------------------------------------------------------------


def _search_page(issues: list[dict], next_token: str | None = None) -> dict:
    """Build a fake search API response page."""
    data: dict[str, Any] = {"issues": issues}
    if next_token is not None:
        data["nextPageToken"] = next_token
    return data


class TestFetchTodo:
    def test_empty_jql_returns_empty(self):
        result = fetch_todo(endpoint="x.net", jql="", email="a", token="t")
        assert result == []

    @patch("notegraph.jira._build_session")
    def test_single_page(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.post.return_value = _mock_response(
            _search_page([_SEARCH_ISSUE]),
        )

        result = fetch_todo(
            endpoint="redhat.atlassian.net",
            jql="project = RUN",
            email="a@b.com",
            token="tok",
        )
        assert len(result) == 1
        assert result[0].title == "Fix the widget"

        call_args = session.post.call_args
        body = call_args.kwargs["json"]
        assert body["jql"] == "project = RUN"
        assert "nextPageToken" not in body

    @patch("notegraph.jira._build_session")
    def test_pagination(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session

        issue_a = {
            "key": "RUN-1",
            "fields": {
                "summary": "Older",
                "status": {"name": "Open"},
                "issuetype": {"name": "Task"},
                "project": {"key": "RUN"},
                "updated": "2026-04-01T00:00:00.000+0000",
            },
        }
        issue_b = {
            "key": "RUN-2",
            "fields": {
                "summary": "Newer",
                "status": {"name": "Open"},
                "issuetype": {"name": "Story"},
                "project": {"key": "RUN"},
                "updated": "2026-04-10T00:00:00.000+0000",
            },
        }

        session.post.return_value.__enter__ = MagicMock()
        session.post.side_effect = [
            _mock_response(_search_page([issue_a], next_token="page2")),
            _mock_response(_search_page([issue_b])),
        ]

        result = fetch_todo(
            endpoint="redhat.atlassian.net",
            jql="project = RUN",
        )
        assert len(result) == 2
        assert result[0].title == "Newer"
        assert result[1].title == "Older"

        second_call_body = session.post.call_args_list[1].kwargs["json"]
        assert second_call_body["nextPageToken"] == "page2"

    @patch("notegraph.jira._build_session")
    def test_api_error_raises(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.post.return_value = _mock_response(
            {"errors": "bad"},
            ok=False,
            status_code=400,
        )

        with pytest.raises(FetchError, match="400"):
            fetch_todo(
                endpoint="redhat.atlassian.net",
                jql="invalid jql",
            )

    @patch("notegraph.jira._build_session")
    def test_credentials_forwarded(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.post.return_value = _mock_response(_search_page([]))

        fetch_todo(
            endpoint="x.net",
            jql="project = X",
            email="me@x.com",
            token="secret",
        )
        mock_build.assert_called_once_with("me@x.com", "secret")

    @patch("notegraph.jira._build_session")
    def test_empty_result(self, mock_build):
        session = MagicMock()
        mock_build.return_value = session
        session.post.return_value = _mock_response(_search_page([]))

        result = fetch_todo(endpoint="x.net", jql="project = X")
        assert result == []
