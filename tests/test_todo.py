"""Unit tests for notegraph.todo — worktodo page generation."""

from __future__ import annotations

from datetime import UTC, datetime

from notegraph.schema import TodoItem
from notegraph.todo import (
    WorktodoPage,
    item_to_line,
    item_to_wikilink,
    merge_worktodo,
    parse_worktodo,
    write_worktodo,
)

# ---------------------------------------------------------------------------
# item_to_wikilink
# ---------------------------------------------------------------------------


class TestItemToWikilink:
    def test_github_pr(self):
        item = TodoItem(
            url="https://github.com/containers/podman/pull/123",
            title="Fix",
            source="github",
            kind="pull_request",
            state="open",
        )
        assert item_to_wikilink(item) == "github.com/containers/podman/pull/123"

    def test_github_issue(self):
        item = TodoItem(
            url="https://github.com/o/r/issues/42",
            title="Bug",
            source="github",
            kind="issue",
            state="open",
        )
        assert item_to_wikilink(item) == "github.com/o/r/issues/42"

    def test_jira(self):
        item = TodoItem(
            url="https://redhat.atlassian.net/browse/RUN-100",
            title="Story",
            source="jira",
            kind="story",
            state="Open",
        )
        assert item_to_wikilink(item) == "redhat.atlassian.net/RUN-100"

    def test_unknown_url_passthrough(self):
        item = TodoItem(
            url="https://custom.example.com/ticket/1",
            title="Custom",
            source="github",
            kind="issue",
            state="open",
        )
        assert item_to_wikilink(item) == "https://custom.example.com/ticket/1"


# ---------------------------------------------------------------------------
# item_to_line
# ---------------------------------------------------------------------------


class TestItemToLine:
    def test_github(self):
        item = TodoItem(
            url="https://github.com/o/r/pull/1",
            title="Fix bug",
            source="github",
            kind="pull_request",
            state="open",
        )
        result = item_to_line(item)
        assert result == "- [[github.com/o/r/pull/1]] Fix bug (**open**)"

    def test_jira_includes_key(self):
        item = TodoItem(
            url="https://test.atlassian.net/browse/RUN-50",
            title="Add caching",
            source="jira",
            kind="story",
            state="In Progress",
        )
        result = item_to_line(item)
        assert result == "- [[test.atlassian.net/RUN-50]] RUN-50 Add caching (**In Progress**)"


# ---------------------------------------------------------------------------
# parse_worktodo
# ---------------------------------------------------------------------------


class TestParseWorktodo:
    def test_missing_file(self, tmp_path):
        page = parse_worktodo(tmp_path / "missing.md")
        assert page == WorktodoPage()

    def test_empty_file(self, tmp_path):
        p = tmp_path / "worktodo.md"
        p.write_text("", encoding="utf-8")
        page = parse_worktodo(p)
        assert page.focus == []
        assert page.backlog == []
        assert page.incoming == []

    def test_full_parse(self, tmp_path):
        p = tmp_path / "worktodo.md"
        p.write_text(
            "# Worktodo\n"
            "\n"
            "## Focus\n"
            "\n"
            "- [[github.com/o/r/pull/1]] Fix bug (**open**)\n"
            "\n"
            "## Backlog\n"
            "\n"
            "- [[test.atlassian.net/RUN-50]] RUN-50 Story (**Open**)\n"
            "\n"
            "## Incoming\n"
            "\n"
            "- [[github.com/x/y/issues/9]] New feature (**open**)\n",
            encoding="utf-8",
        )
        page = parse_worktodo(p)
        assert page.focus == ["github.com/o/r/pull/1"]
        assert page.backlog == ["test.atlassian.net/RUN-50"]
        assert page.incoming == ["github.com/x/y/issues/9"]
        assert len(page.items) == 3

    def test_items_contain_full_lines(self, tmp_path):
        p = tmp_path / "worktodo.md"
        p.write_text(
            "## Focus\n"
            "- [[github.com/o/r/pull/1]] Fix (**open**)\n",
            encoding="utf-8",
        )
        page = parse_worktodo(p)
        assert page.items["github.com/o/r/pull/1"] == "- [[github.com/o/r/pull/1]] Fix (**open**)"


# ---------------------------------------------------------------------------
# merge_worktodo
# ---------------------------------------------------------------------------

_FRESH_ITEMS = [
    TodoItem(
        url="https://github.com/o/r/pull/1",
        title="Fix bug",
        source="github",
        kind="pull_request",
        state="open",
    ),
    TodoItem(
        url="https://github.com/o/r/issues/2",
        title="Feature",
        source="github",
        kind="issue",
        state="open",
    ),
    TodoItem(
        url="https://test.atlassian.net/browse/RUN-50",
        title="Story",
        source="jira",
        kind="story",
        state="Open",
    ),
]


class TestMergeWorktodo:
    def test_empty_existing(self):
        merged = merge_worktodo(WorktodoPage(), _FRESH_ITEMS)
        assert merged.focus == []
        assert merged.backlog == []
        assert len(merged.incoming) == 3

    def test_preserves_focus_order(self):
        existing = WorktodoPage(
            focus=["github.com/o/r/pull/1", "test.atlassian.net/RUN-50"],
            items={
                "github.com/o/r/pull/1": "- [[github.com/o/r/pull/1]] old",
                "test.atlassian.net/RUN-50": "- [[test.atlassian.net/RUN-50]] old",
            },
        )
        merged = merge_worktodo(existing, _FRESH_ITEMS)
        assert merged.focus == ["github.com/o/r/pull/1", "test.atlassian.net/RUN-50"]
        assert "github.com/o/r/issues/2" in merged.incoming

    def test_drops_stale_items(self):
        existing = WorktodoPage(
            focus=["github.com/stale/item/pull/999"],
            items={"github.com/stale/item/pull/999": "- [[github.com/stale/item/pull/999]] old"},
        )
        merged = merge_worktodo(existing, _FRESH_ITEMS)
        assert merged.focus == []
        assert "github.com/stale/item/pull/999" not in merged.items

    def test_backlog_preserved(self):
        existing = WorktodoPage(
            backlog=["github.com/o/r/issues/2"],
            items={"github.com/o/r/issues/2": "- [[github.com/o/r/issues/2]] old"},
        )
        merged = merge_worktodo(existing, _FRESH_ITEMS)
        assert merged.backlog == ["github.com/o/r/issues/2"]
        assert "github.com/o/r/issues/2" not in merged.incoming

    def test_items_updated_with_fresh_lines(self):
        existing = WorktodoPage(
            focus=["github.com/o/r/pull/1"],
            items={"github.com/o/r/pull/1": "- [[github.com/o/r/pull/1]] OLD"},
        )
        merged = merge_worktodo(existing, _FRESH_ITEMS)
        assert "Fix bug" in merged.items["github.com/o/r/pull/1"]


# ---------------------------------------------------------------------------
# write_worktodo
# ---------------------------------------------------------------------------


class TestWriteWorktodo:
    def test_roundtrip(self, tmp_path):
        page = WorktodoPage(
            focus=["github.com/o/r/pull/1"],
            backlog=["test.atlassian.net/RUN-50"],
            incoming=["github.com/x/y/issues/9"],
            items={
                "github.com/o/r/pull/1": "- [[github.com/o/r/pull/1]] Fix (**open**)",
                "test.atlassian.net/RUN-50": (
                    "- [[test.atlassian.net/RUN-50]] RUN-50 Story (**Open**)"
                ),
                "github.com/x/y/issues/9": "- [[github.com/x/y/issues/9]] New (**open**)",
            },
        )
        p = tmp_path / "worktodo.md"
        write_worktodo(page, p)

        reparsed = parse_worktodo(p)
        assert reparsed.focus == page.focus
        assert reparsed.backlog == page.backlog
        assert reparsed.incoming == page.incoming

    def test_date_stamp(self, tmp_path):
        page = WorktodoPage()
        p = tmp_path / "worktodo.md"
        write_worktodo(page, p)
        text = p.read_text(encoding="utf-8")
        assert datetime.now(tz=UTC).date().isoformat() in text

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "worktodo.md"
        write_worktodo(WorktodoPage(), p)
        assert p.is_file()
