"""Exhaustive tests for all schema models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from notegraph.schema import (
    Comment,
    FileStatus,
    GitHubRef,
    JiraRef,
    NoteBody,
    NoteContent,
    NoteHeader,
    NoteTags,
    NoteTriplet,
    PathInfo,
    Section,
)

# ===================================================================
# GitHubRef
# ===================================================================


class TestGitHubRefFromUrl:
    def test_valid_pr_url(self):
        ref = GitHubRef.from_url("https://github.com/containers/podman/pull/24126")
        assert ref.org == "containers"
        assert ref.repo == "podman"
        assert ref.url_type == "pull"
        assert ref.number == 24126

    def test_valid_issue_url(self):
        ref = GitHubRef.from_url("https://github.com/org/repo/issues/999")
        assert ref.org == "org"
        assert ref.repo == "repo"
        assert ref.url_type == "issues"
        assert ref.number == 999

    def test_url_with_trailing_content(self):
        ref = GitHubRef.from_url(
            "https://github.com/org/repo/pull/1#issuecomment-123",
        )
        assert ref.number == 1

    def test_wrong_host(self):
        with pytest.raises(ValueError, match="does not match"):
            GitHubRef.from_url("https://gitlab.com/org/repo/pull/1")

    def test_missing_number(self):
        with pytest.raises(ValueError, match="does not match"):
            GitHubRef.from_url("https://github.com/org/repo/pull/")

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="does not match"):
            GitHubRef.from_url("https://github.com/org/repo/wiki/1")

    def test_completely_invalid(self):
        with pytest.raises(ValueError, match="does not match"):
            GitHubRef.from_url("not-a-url")

    def test_note_type_pr(self):
        ref = GitHubRef.from_url("https://github.com/o/r/pull/1")
        assert ref.note_type == "pull_request"

    def test_note_type_issue(self):
        ref = GitHubRef.from_url("https://github.com/o/r/issues/1")
        assert ref.note_type == "issue"

    def test_canonical_url(self):
        ref = GitHubRef.from_url("https://github.com/org/repo/pull/42")
        assert ref.canonical_url == "https://github.com/org/repo/pull/42"


# ===================================================================
# JiraRef
# ===================================================================


class TestJiraRefFromString:
    def test_bare_key(self):
        ref = JiraRef.from_string("RUN-3555", default_endpoint="test.atlassian.net")
        assert ref.endpoint == "test.atlassian.net"
        assert ref.key == "RUN-3555"

    def test_full_url(self):
        ref = JiraRef.from_string(
            "https://redhat.atlassian.net/browse/RUN-100",
            default_endpoint="unused",
        )
        assert ref.endpoint == "redhat.atlassian.net"
        assert ref.key == "RUN-100"

    def test_lowercase_normalization(self):
        ref = JiraRef.from_string("run-3555", default_endpoint="host")
        assert ref.key == "RUN-3555"

    def test_invalid_input(self):
        with pytest.raises(ValueError, match="Not a valid"):
            JiraRef.from_string("not-valid-at-all", default_endpoint="host")

    def test_invalid_no_number(self):
        with pytest.raises(ValueError, match="Not a valid"):
            JiraRef.from_string("RUN-", default_endpoint="host")

    def test_browse_url(self):
        ref = JiraRef(endpoint="test.atlassian.net", key="RUN-3555")
        assert ref.browse_url == "https://test.atlassian.net/browse/RUN-3555"


# ===================================================================
# FileStatus / NoteTriplet
# ===================================================================


class TestNoteTriplet:
    def test_model_dump_matches_check_json_shape(self):
        triplet = NoteTriplet(
            md=FileStatus(path="/p/foo.md", exists=True),
            note=FileStatus(path="/p/foo___note.md", exists=False),
            cursor=FileStatus(path="/p/foo___cursor.md", exists=True),
        )
        dumped = triplet.model_dump()
        assert dumped == {
            "md": {"path": "/p/foo.md", "exists": True},
            "note": {"path": "/p/foo___note.md", "exists": False},
            "cursor": {"path": "/p/foo___cursor.md", "exists": True},
        }

    def test_model_dump_json_is_valid(self):
        triplet = NoteTriplet(
            md=FileStatus(path="/a.md", exists=False),
            note=FileStatus(path="/a___note.md", exists=False),
            cursor=FileStatus(path="/a___cursor.md", exists=False),
        )
        parsed = json.loads(triplet.model_dump_json())
        assert parsed["md"]["exists"] is False

    def test_format_table_contains_all_kinds(self):
        triplet = NoteTriplet(
            md=FileStatus(path="/p/foo.md", exists=True),
            note=FileStatus(path="/p/foo___note.md", exists=False),
            cursor=FileStatus(path="/p/foo___cursor.md", exists=True),
        )
        table = triplet.format_table()
        assert "Kind" in table
        assert "Exists" in table
        assert "Path" in table
        assert "md" in table
        assert "note" in table
        assert "cursor" in table

    def test_format_table_check_mark_for_exists(self):
        triplet = NoteTriplet(
            md=FileStatus(path="/p/foo.md", exists=True),
            note=FileStatus(path="/p/foo___note.md", exists=False),
            cursor=FileStatus(path="/p/foo___cursor.md", exists=False),
        )
        table = triplet.format_table()
        lines = table.strip().splitlines()
        md_line = next(row for row in lines if row.strip().startswith("md"))
        note_line = next(row for row in lines if row.strip().startswith("note"))
        assert "\u2713" in md_line
        assert "\u2717" in note_line

    def test_format_table_contains_paths(self):
        triplet = NoteTriplet(
            md=FileStatus(path="/some/dir/file.md", exists=False),
            note=FileStatus(path="/some/dir/file___note.md", exists=False),
            cursor=FileStatus(path="/some/dir/file___cursor.md", exists=False),
        )
        table = triplet.format_table()
        assert "/some/dir/file.md" in table
        assert "/some/dir/file___note.md" in table
        assert "/some/dir/file___cursor.md" in table


# ===================================================================
# PathInfo — GitHub
# ===================================================================


class TestPathInfoFromGithub:
    def test_logseq_paths(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/dest")
        assert pi.file_prefix == "/dest/github.com___containers___podman___pull___24126"
        assert pi.file_sep == "___"
        assert pi.wikilink_prefix == "github.com/containers/podman/pull/24126"
        assert pi.wikilink_sep == "/"

    def test_derived_md_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d")
        assert pi.md_path == "/d/github.com___containers___podman___pull___24126.md"

    def test_derived_note_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d")
        assert pi.note_path == "/d/github.com___containers___podman___pull___24126___note.md"

    def test_derived_cursor_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d")
        assert pi.cursor_path == "/d/github.com___containers___podman___pull___24126___cursor.md"

    def test_wikilinks(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d")
        assert pi.wikilink == "github.com/containers/podman/pull/24126"
        assert pi.wikilink_note == "github.com/containers/podman/pull/24126/note"
        assert pi.wikilink_cursor == "github.com/containers/podman/pull/24126/cursor"

    def test_path_for(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d")
        assert pi.path_for("md") == pi.md_path
        assert pi.path_for("note") == pi.note_path
        assert pi.path_for("cursor") == pi.cursor_path


# ===================================================================
# PathInfo — Jira
# ===================================================================


class TestPathInfoFromJira:
    def test_logseq_paths(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest")
        assert pi.file_prefix == "/dest/test.atlassian.net___RUN-3555"
        assert pi.file_sep == "___"

    def test_wikilinks(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest")
        assert pi.wikilink == "test.atlassian.net/RUN-3555"
        assert pi.wikilink_note == "test.atlassian.net/RUN-3555/note"
        assert pi.wikilink_cursor == "test.atlassian.net/RUN-3555/cursor"

    def test_md_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest")
        assert pi.md_path == "/dest/test.atlassian.net___RUN-3555.md"

    def test_note_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest")
        assert pi.note_path == "/dest/test.atlassian.net___RUN-3555___note.md"

    def test_cursor_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest")
        assert pi.cursor_path == "/dest/test.atlassian.net___RUN-3555___cursor.md"


# ===================================================================
# PathInfo.from_ref dispatch
# ===================================================================


class TestPathInfoFromRef:
    def test_dispatches_to_github(self, sample_github_ref):
        pi = PathInfo.from_ref(sample_github_ref, "/d")
        assert "github.com" in pi.file_prefix

    def test_dispatches_to_jira(self, sample_jira_ref):
        pi = PathInfo.from_ref(sample_jira_ref, "/d")
        assert "test.atlassian.net" in pi.file_prefix


# ===================================================================
# PathInfo.to_triplet — file existence
# ===================================================================


class TestPathInfoToTriplet:
    def test_no_files_exist(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        triplet = pi.to_triplet()
        assert triplet.md.exists is False
        assert triplet.note.exists is False
        assert triplet.cursor.exists is False

    def test_all_files_exist(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        for path in (pi.md_path, pi.note_path, pi.cursor_path):
            Path(path).write_text("content", encoding="utf-8")

        triplet = pi.to_triplet()
        assert triplet.md.exists is True
        assert triplet.note.exists is True
        assert triplet.cursor.exists is True

    def test_partial_existence(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.md_path).write_text("x", encoding="utf-8")

        triplet = pi.to_triplet()
        assert triplet.md.exists is True
        assert triplet.note.exists is False
        assert triplet.cursor.exists is False

    def test_paths_in_triplet_match(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        triplet = pi.to_triplet()
        assert triplet.md.path == pi.md_path
        assert triplet.note.path == pi.note_path
        assert triplet.cursor.path == pi.cursor_path


# ===================================================================
# NoteContent / Comment
# ===================================================================


class TestNoteContent:
    def test_roundtrip(self, sample_note_content):
        data = sample_note_content.model_dump()
        restored = NoteContent.model_validate(data)
        assert restored.title == sample_note_content.title
        assert len(restored.comments) == 2
        assert restored.extra["mergedAt"] is None

    def test_defaults(self):
        content = NoteContent(
            title="t",
            url="u",
            source="github",
            status="open",
            author="a",
            created="2024-01-01",
            description="d",
        )
        assert content.comments == []
        assert content.note_type == "issue"
        assert content.extra == {}


class TestComment:
    def test_basic(self):
        c = Comment(author="user", date="2024-01-01", body="hello")
        assert c.author == "user"

    def test_empty_body(self):
        c = Comment(author="u", date="d", body="")
        assert c.body == ""

    def test_special_chars_in_author(self):
        c = Comment(author="user@host [bot]", date="d", body="b")
        assert c.author == "user@host [bot]"


# ===================================================================
# NoteHeader — from_content and to_string
# ===================================================================


class TestNoteHeader:
    def test_from_content_md(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "md")
        assert header.title == sample_note_content.title
        assert "cursor" in header.wikilinks[0]
        assert "note" in header.wikilinks[1]

    def test_from_content_note(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "note")
        assert "cursor" in header.wikilinks[0]
        assert header.wikilinks[1] == paths.wikilink

    def test_from_content_cursor(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "cursor")
        assert header.wikilinks[0] == paths.wikilink
        assert "note" in header.wikilinks[1]

    def test_to_string_cursor(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "cursor")
        rendered = header.to_string("cursor")
        assert rendered.startswith("# Fix container networking regression")
        assert "**Type:** pull_request" in rendered
        assert "**Status:** open" in rendered
        assert "**Author:** developer" in rendered
        assert "**Created:** 2024-03-15" in rendered

    def test_to_string_md(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "md")
        rendered = header.to_string("md")
        assert "# Fix container networking regression" in rendered
        assert sample_note_content.url in rendered

    def test_to_string_note(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "note")
        rendered = header.to_string("note")
        assert "# Fix container networking regression" in rendered


# ===================================================================
# NoteBody — from_content and to_string
# ===================================================================


class TestNoteBody:
    def test_from_content_md(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "md")
        assert body.description == sample_note_content.description
        assert len(body.comments) == 2
        assert body.sections[0].heading == "Key Discussion Points"

    def test_from_content_note(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "note")
        headings = [s.heading for s in body.sections]
        assert headings == ["Notes", "TODOs", "Related"]

    def test_from_content_cursor(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "cursor")
        headings = [s.heading for s in body.sections]
        assert headings == ["Analysis", "TODOs"]

    def test_to_string_md(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "md")
        rendered = body.to_string("md")
        assert "## Description" in rendered
        assert "## Comments" in rendered
        assert "### @reviewer1 (2024-03-16)" in rendered
        assert "LGTM, minor nit on line 42." in rendered
        assert "### @reviewer2 (2024-03-17)" in rendered
        assert "## Key Discussion Points" in rendered
        assert "<!-- summarize the above comments here -->" in rendered

    def test_to_string_note(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "note")
        rendered = body.to_string("note")
        assert "## Notes" in rendered
        assert "## TODOs" in rendered
        assert "## Related" in rendered

    def test_to_string_cursor(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "cursor")
        rendered = body.to_string("cursor")
        assert "## Analysis" in rendered
        assert "## TODOs" in rendered

    def test_to_string_md_no_comments(self):
        content = NoteContent(
            title="t",
            url="u",
            source="github",
            status="open",
            author="a",
            created="d",
            description="desc",
        )
        body = NoteBody.from_content(content, "md")
        rendered = body.to_string("md")
        assert "## Comments" in rendered
        assert "###" not in rendered


# ===================================================================
# Section model
# ===================================================================


class TestSection:
    def test_default_content(self):
        s = Section(heading="Analysis")
        assert s.content == ""

    def test_with_content(self):
        s = Section(heading="Notes", content="some text")
        assert s.content == "some text"


# ===================================================================
# NoteTags
# ===================================================================


class TestNoteTags:
    def test_from_github_ref_pr(self, sample_github_ref):
        tags = NoteTags.from_github_ref(sample_github_ref)
        assert tags.source == "github"
        assert tags.kind == "pull_request"
        assert tags.org_repo == "containers/podman"

    def test_from_github_ref_issue(self):
        ref = GitHubRef(org="org", repo="repo", url_type="issues", number=42)
        tags = NoteTags.from_github_ref(ref)
        assert tags.kind == "issue"
        assert tags.org_repo == "org/repo"

    def test_from_jira_content(self, sample_jira_content):
        tags = NoteTags.from_jira_content(sample_jira_content)
        assert tags.source == "jira"
        assert tags.kind == "issue"
        assert tags.org_repo == ""

    def test_from_jira_content_story(self):
        content = NoteContent(
            title="t",
            url="u",
            source="jira",
            status="s",
            author="a",
            created="d",
            description="d",
            note_type="story",
        )
        tags = NoteTags.from_jira_content(content)
        assert tags.kind == "story"
