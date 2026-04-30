"""Tests for Vikunja waiting sync helpers."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import requests as _req

from notegraph.schema import TodoItem
from notegraph.vikunja_sync import (
    VikunjaClient,
    _canonical_sync_id,
    _extract_sync_id,
    _github_sync_slug,
    _jira_priority_to_vikunja,
    _jira_sync_slug,
    _waiting_from_github_todo,
    _waiting_from_jira_todo,
    _weekly_reminders,
)


class TestGithubSyncSlug:
    def test_issue_vs_pull(self) -> None:
        assert _github_sync_slug("containers/podman", "42", is_pull=False) == (
            "github-containers-podman-issue-42"
        )
        assert _github_sync_slug("containers/podman", "42", is_pull=True) == (
            "github-containers-podman-pull-42"
        )

    def test_slug_segments(self) -> None:
        assert _github_sync_slug("My_Org/hello.world", "1", is_pull=False) == (
            "github-my-org-hello-world-issue-1"
        )


class TestJiraSyncSlug:
    def test_basic(self) -> None:
        assert _jira_sync_slug("RUN-3555") == "jira-run-3555"


class TestCanonicalSyncId:
    def test_passes_through_slug(self) -> None:
        assert _canonical_sync_id("github-a-b-issue-1", "") == "github-a-b-issue-1"
        assert _canonical_sync_id("jira-run-1", "") == "jira-run-1"

    def test_legacy_jira(self) -> None:
        assert _canonical_sync_id("jira:RUN-100", "") == "jira-run-100"

    def test_legacy_github_issue(self) -> None:
        desc = "[t](https://github.com/o/r/issues/5)"
        assert _canonical_sync_id("github:o/r#5", desc) == "github-o-r-issue-5"

    def test_legacy_github_pull(self) -> None:
        desc = "[t](https://github.com/o/r/pull/5)"
        assert _canonical_sync_id("github:o/r#5", desc) == "github-o-r-pull-5"


class TestExtractSyncId:
    def test_roundtrip_slug(self) -> None:
        desc = "<!-- notegraph-sync id=github-acme-r-issue-9 -->\n\nbody"
        assert _extract_sync_id(desc) == "github-acme-r-issue-9"

    def test_legacy_normalized(self) -> None:
        desc = (
            "<!-- notegraph-sync id=github:acme/r#9 -->\n\n"
            "[x](https://github.com/acme/r/issues/9)"
        )
        assert _extract_sync_id(desc) == "github-acme-r-issue-9"


class TestWaitingFromTodoTitles:
    def test_github_title_is_sync_slug(self) -> None:
        item = TodoItem(
            url="https://github.com/acme/r/issues/9",
            title="Human title",
            source="github",
            kind="issue",
            state="open",
            repo="acme/r",
        )
        row = _waiting_from_github_todo(item, project_template="{repo}")
        assert row is not None
        assert row.title == "github-acme-r-issue-9"
        assert "Human title" in row.description
        assert "[github-acme-r-issue-9]" in row.description

    def test_github_pull_title_is_sync_slug(self) -> None:
        item = TodoItem(
            url="https://github.com/acme/r/pull/9",
            title="PR title",
            source="github",
            kind="pull_request",
            state="open",
            repo="acme/r",
        )
        row = _waiting_from_github_todo(item, project_template="{repo}")
        assert row is not None
        assert row.title == "github-acme-r-pull-9"

    def test_github_default_project_is_github(self) -> None:
        item = TodoItem(
            url="https://github.com/acme/r/issues/1",
            title="t",
            source="github",
            kind="issue",
            state="open",
            repo="acme/r",
        )
        row = _waiting_from_github_todo(item, project_template="GitHub")
        assert row is not None
        assert row.vikunja_project_title == "GitHub"

    def test_jira_title_is_issue_key(self) -> None:
        item = TodoItem(
            url="https://jira.example.com/browse/RUN-100",
            title="Human summary",
            source="jira",
            kind="story",
            state="Open",
            repo="RUN",
        )
        row = _waiting_from_jira_todo(item, project_template="{project_key}")
        assert row is not None
        assert row.title == "RUN-100"
        assert "Human summary" in row.description
        assert "[RUN-100]" in row.description

    def test_jira_default_project_is_jira(self) -> None:
        item = TodoItem(
            url="https://jira.example.com/browse/RUN-100",
            title="t",
            source="jira",
            kind="story",
            state="Open",
            repo="RUN",
        )
        row = _waiting_from_jira_todo(item, project_template="JIRA")
        assert row is not None
        assert row.vikunja_project_title == "JIRA"


class TestVikunjaClientIterTasks:
    def test_iter_tasks_returns_empty_without_fallback(self) -> None:
        """GET /tasks returning [] should NOT trigger /tasks/all fallback."""
        session = MagicMock()
        empty = MagicMock()
        empty.json.return_value = []
        empty.raise_for_status = MagicMock()
        session.get.return_value = empty

        client = VikunjaClient("http://localhost/api/v1", "tok", session=session)
        tasks = client.iter_tasks(per_page=100)
        assert tasks == []
        session.get.assert_called_once()

    def test_iter_tasks_falls_back_on_404(self) -> None:
        """GET /tasks 404 → retry with /tasks/all."""
        session = MagicMock()
        not_found = MagicMock()
        not_found.status_code = 404
        not_found.raise_for_status.side_effect = _req.HTTPError(response=not_found)

        legacy_batch = MagicMock()
        legacy_batch.json.return_value = [{"id": 1, "project_id": 1, "description": ""}]
        legacy_batch.raise_for_status = MagicMock()
        session.get.side_effect = [not_found, legacy_batch]

        client = VikunjaClient("http://localhost/api/v1", "tok", session=session)
        tasks = client.iter_tasks(per_page=100)
        assert len(tasks) == 1
        assert session.get.call_count == 2
        assert "/tasks/all" in session.get.call_args_list[1][0][0]

    def test_iter_tasks_primary_returns_tasks(self) -> None:
        session = MagicMock()
        ok = MagicMock()
        ok.json.return_value = [{"id": 2, "project_id": 1, "description": ""}]
        ok.raise_for_status = MagicMock()
        session.get.return_value = ok

        client = VikunjaClient("http://localhost/api/v1", "tok", session=session)
        tasks = client.iter_tasks(per_page=100)
        assert len(tasks) == 1
        session.get.assert_called_once()
        assert session.get.call_args[0][0].endswith("/tasks")


class TestWeeklyReminders:
    def _now(self) -> datetime.datetime:
        return datetime.datetime(2026, 4, 30, tzinfo=datetime.timezone.utc)

    def test_empty_start_returns_empty(self) -> None:
        assert _weekly_reminders("") == []

    def test_invalid_date_returns_empty(self) -> None:
        assert _weekly_reminders("not-a-date") == []

    def test_less_than_seven_days_returns_empty(self) -> None:
        start = "2026-04-25T00:00:00Z"  # 5 days ago
        assert _weekly_reminders(start, now=self._now()) == []

    def test_exactly_seven_days_returns_one(self) -> None:
        start = "2026-04-23T00:00:00Z"  # 7 days ago
        result = _weekly_reminders(start, now=self._now())
        assert len(result) == 1
        assert result[0]["reminder"] == "2026-04-30T00:00:00Z"

    def test_three_weeks_returns_three(self) -> None:
        start = "2026-04-09T00:00:00Z"  # 21 days ago
        result = _weekly_reminders(start, now=self._now())
        assert len(result) == 3
        assert result[0]["reminder"] == "2026-04-16T00:00:00Z"
        assert result[1]["reminder"] == "2026-04-23T00:00:00Z"
        assert result[2]["reminder"] == "2026-04-30T00:00:00Z"

    def test_reminder_shape(self) -> None:
        start = "2026-04-23T00:00:00Z"
        result = _weekly_reminders(start, now=self._now())
        assert len(result) == 1
        r = result[0]
        assert r["relative_period"] == 0
        assert r["relative_to"] == "due_date"


class TestJiraPriorityMapping:
    def test_known_priorities(self) -> None:
        assert _jira_priority_to_vikunja("Blocker") == 4
        assert _jira_priority_to_vikunja("Highest") == 4
        assert _jira_priority_to_vikunja("Critical") == 3
        assert _jira_priority_to_vikunja("High") == 3
        assert _jira_priority_to_vikunja("Major") == 2
        assert _jira_priority_to_vikunja("Medium") == 2
        assert _jira_priority_to_vikunja("Minor") == 1
        assert _jira_priority_to_vikunja("Low") == 1
        assert _jira_priority_to_vikunja("Trivial") == 0

    def test_unknown_returns_zero(self) -> None:
        assert _jira_priority_to_vikunja("") == 0
        assert _jira_priority_to_vikunja("Custom Priority") == 0

    def test_case_insensitive(self) -> None:
        assert _jira_priority_to_vikunja("MAJOR") == 2
        assert _jira_priority_to_vikunja("major") == 2
        assert _jira_priority_to_vikunja("  Major  ") == 2


class TestJiraPriorityInWaiting:
    def test_jira_priority_passed_through(self) -> None:
        item = TodoItem(
            url="https://jira.example.com/browse/RUN-100",
            title="t",
            source="jira",
            kind="story",
            state="Open",
            repo="RUN",
            priority="Major",
        )
        row = _waiting_from_jira_todo(item, project_template="JIRA")
        assert row is not None
        assert row.priority == 2

    def test_github_priority_is_zero(self) -> None:
        item = TodoItem(
            url="https://github.com/acme/r/issues/1",
            title="t",
            source="github",
            kind="issue",
            state="open",
            repo="acme/r",
        )
        row = _waiting_from_github_todo(item, project_template="GitHub")
        assert row is not None
        assert row.priority == 0
