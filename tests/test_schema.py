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
        pi = PathInfo.from_github(sample_github_ref, "/dest", "logseq")
        assert pi.file_prefix == "/dest/github.com___containers___podman___pull___24126"
        assert pi.file_sep == "___"
        assert pi.wikilink_prefix == "github.com/containers/podman/pull/24126"
        assert pi.wikilink_sep == "/"

    def test_derived_md_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        assert pi.md_path == "/d/github.com___containers___podman___pull___24126.md"

    def test_derived_note_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        assert pi.note_path == "/d/github.com___containers___podman___pull___24126___note.md"

    def test_derived_cursor_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        assert pi.cursor_path == "/d/github.com___containers___podman___pull___24126___cursor.md"

    def test_wikilinks(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        assert pi.wikilink == "github.com/containers/podman/pull/24126"
        assert pi.wikilink_note == "github.com/containers/podman/pull/24126/note"
        assert pi.wikilink_cursor == "github.com/containers/podman/pull/24126/cursor"

    def test_path_for(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        assert pi.path_for("md") == pi.md_path
        assert pi.path_for("note") == pi.note_path
        assert pi.path_for("cursor") == pi.cursor_path

    def test_cosma_paths(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        assert pi.file_prefix == "/d/github-containers-podman-pull-24126"
        assert pi.file_sep == "-"
        assert pi.md_path == "/d/github-containers-podman-pull-24126.md"
        assert pi.note_path == "/d/github-containers-podman-pull-24126-note.md"
        assert pi.cursor_path == "/d/github-containers-podman-pull-24126-cursor.md"
        assert len(pi.cosma_ids) == 3
        assert all(len(v) == 14 and v.isdigit() for v in pi.cosma_ids.values())


# ===================================================================
# PathInfo — Jira
# ===================================================================


class TestPathInfoFromJira:
    def test_logseq_paths(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest", "logseq")
        assert pi.file_prefix == "/dest/test.atlassian.net___RUN-3555"
        assert pi.file_sep == "___"

    def test_wikilinks(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest", "logseq")
        assert pi.wikilink == "test.atlassian.net/RUN-3555"
        assert pi.wikilink_note == "test.atlassian.net/RUN-3555/note"
        assert pi.wikilink_cursor == "test.atlassian.net/RUN-3555/cursor"

    def test_md_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest", "logseq")
        assert pi.md_path == "/dest/test.atlassian.net___RUN-3555.md"

    def test_note_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest", "logseq")
        assert pi.note_path == "/dest/test.atlassian.net___RUN-3555___note.md"

    def test_cursor_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest", "logseq")
        assert pi.cursor_path == "/dest/test.atlassian.net___RUN-3555___cursor.md"

    def test_cosma_paths(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/d", "cosma")
        assert pi.file_prefix == "/d/jira-RUN-3555"
        assert pi.file_sep == "-"
        assert pi.md_path == "/d/jira-RUN-3555.md"
        assert pi.note_path == "/d/jira-RUN-3555-note.md"
        assert pi.cursor_path == "/d/jira-RUN-3555-cursor.md"
        assert len(pi.cosma_ids) == 3
        assert all(len(v) == 14 and v.isdigit() for v in pi.cosma_ids.values())


# ===================================================================
# PathInfo.from_ref dispatch
# ===================================================================


class TestPathInfoFromRef:
    def test_dispatches_to_github(self, sample_github_ref):
        pi = PathInfo.from_ref(sample_github_ref, "/d", "logseq")
        assert "github.com" in pi.file_prefix

    def test_dispatches_to_jira(self, sample_jira_ref):
        pi = PathInfo.from_ref(sample_jira_ref, "/d", "logseq")
        assert "test.atlassian.net" in pi.file_prefix


# ===================================================================
# PathInfo.to_triplet — file existence
# ===================================================================


class TestPathInfoToTriplet:
    def test_no_files_exist(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir), "logseq")
        triplet = pi.to_triplet()
        assert triplet.md.exists is False
        assert triplet.note.exists is False
        assert triplet.cursor.exists is False

    def test_all_files_exist(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir), "logseq")
        for path in (pi.md_path, pi.note_path, pi.cursor_path):
            Path(path).write_text("content", encoding="utf-8")

        triplet = pi.to_triplet()
        assert triplet.md.exists is True
        assert triplet.note.exists is True
        assert triplet.cursor.exists is True

    def test_partial_existence(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir), "logseq")
        Path(pi.md_path).write_text("x", encoding="utf-8")

        triplet = pi.to_triplet()
        assert triplet.md.exists is True
        assert triplet.note.exists is False
        assert triplet.cursor.exists is False

    def test_paths_in_triplet_match(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir), "logseq")
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
        paths = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        header = NoteHeader.from_content(sample_note_content, paths, "md")
        assert header.title == sample_note_content.title
        assert "cursor" in header.wikilinks[0]
        assert "note" in header.wikilinks[1]

    def test_from_content_note(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        header = NoteHeader.from_content(sample_note_content, paths, "note")
        assert "cursor" in header.wikilinks[0]
        assert header.wikilinks[1] == paths.wikilink

    def test_from_content_cursor(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        header = NoteHeader.from_content(sample_note_content, paths, "cursor")
        assert header.wikilinks[0] == paths.wikilink
        assert "note" in header.wikilinks[1]

    def test_to_string_logseq_cursor(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        header = NoteHeader.from_content(sample_note_content, paths, "cursor")
        rendered = header.to_string("logseq", "cursor")
        assert rendered.startswith("# Fix container networking regression")
        assert "**Type:** pull_request" in rendered
        assert "**Status:** open" in rendered
        assert "**Author:** developer" in rendered
        assert "**Created:** 2024-03-15" in rendered

    def test_to_string_logseq_md(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        header = NoteHeader.from_content(sample_note_content, paths, "md")
        rendered = header.to_string("logseq", "md")
        assert "# Fix container networking regression" in rendered
        assert sample_note_content.url in rendered

    def test_to_string_logseq_note(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d", "logseq")
        header = NoteHeader.from_content(sample_note_content, paths, "note")
        rendered = header.to_string("logseq", "note")
        assert "# Fix container networking regression" in rendered

    def test_to_string_cosma_md(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        tags = NoteTags.from_github_ref(sample_github_ref)
        header = NoteHeader.from_content(
            sample_note_content,
            paths,
            "md",
            fmt="cosma",
            tags=tags,
        )
        rendered = header.to_string("cosma", "md")
        assert rendered.startswith("---\n")
        assert 'title: "Fix container networking regression"' in rendered
        assert f"id: {paths.cosma_ids['md']}" in rendered
        assert "type: summary" in rendered
        assert "author: developer" in rendered
        assert "- github" in rendered
        assert "- pull_request" in rendered
        assert "- containers/podman" in rendered
        assert "---" in rendered.split("\n", 1)[1]


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

    def test_to_string_logseq_md(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "md")
        rendered = body.to_string("logseq", "md")
        assert "## Description" in rendered
        assert "## Comments" in rendered
        assert "### @reviewer1 (2024-03-16)" in rendered
        assert "LGTM, minor nit on line 42." in rendered
        assert "### @reviewer2 (2024-03-17)" in rendered
        assert "## Key Discussion Points" in rendered
        assert "<!-- summarize the above comments here -->" in rendered

    def test_to_string_logseq_note(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "note")
        rendered = body.to_string("logseq", "note")
        assert "## Notes" in rendered
        assert "## TODOs" in rendered
        assert "## Related" in rendered

    def test_to_string_logseq_cursor(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "cursor")
        rendered = body.to_string("logseq", "cursor")
        assert "## Analysis" in rendered
        assert "## TODOs" in rendered

    def test_to_string_logseq_md_no_comments(self):
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
        rendered = body.to_string("logseq", "md")
        assert "## Comments" in rendered
        assert "###" not in rendered

    def test_to_string_cosma_md(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "md")
        rendered = body.to_string("cosma", "md")
        assert "## Description" in rendered
        assert "## Comments" in rendered


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

    def test_to_cosma_tags_github(self, sample_github_ref):
        tags = NoteTags.from_github_ref(sample_github_ref)
        assert tags.to_cosma_tags() == ["github", "pull_request", "containers/podman"]

    def test_to_cosma_tags_jira(self, sample_jira_content):
        tags = NoteTags.from_jira_content(sample_jira_content)
        assert tags.to_cosma_tags() == ["jira", "issue"]

    def test_to_logseq_tags_placeholder(self, sample_github_ref):
        tags = NoteTags.from_github_ref(sample_github_ref)
        assert tags.to_logseq_tags() == {}


# ===================================================================
# Cosma ID generation
# ===================================================================


class TestCosmaId:
    def test_deterministic(self, sample_github_ref):
        pi1 = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        pi2 = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        assert pi1.cosma_ids == pi2.cosma_ids

    def test_different_per_kind(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        ids = set(pi.cosma_ids.values())
        assert len(ids) == 3

    def test_fourteen_digits(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        for v in pi.cosma_ids.values():
            assert len(v) == 14
            assert v.isdigit()

    def test_different_refs_different_ids(self, sample_github_ref, sample_jira_ref):
        pi_gh = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        pi_jira = PathInfo.from_jira(sample_jira_ref, "/d", "cosma")
        assert pi_gh.cosma_ids["md"] != pi_jira.cosma_ids["md"]

    def test_dest_dir_does_not_affect_ids(self, sample_github_ref):
        pi1 = PathInfo.from_github(sample_github_ref, "/dir1", "cosma")
        pi2 = PathInfo.from_github(sample_github_ref, "/dir2", "cosma")
        assert pi1.cosma_ids == pi2.cosma_ids


# ===================================================================
# PathInfo — Cosma GitHub
# ===================================================================


class TestPathInfoCosmaGithub:
    def test_file_prefix(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/data", "cosma")
        assert pi.file_prefix == "/data/github-containers-podman-pull-24126"

    def test_flat_naming(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/data", "cosma")
        assert "/" not in pi.md_path.removeprefix("/data/")
        assert "/" not in pi.note_path.removeprefix("/data/")
        assert "/" not in pi.cursor_path.removeprefix("/data/")

    def test_file_sep(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        assert pi.file_sep == "-"

    def test_md_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        assert pi.md_path.endswith(".md")
        assert "note" not in pi.md_path
        assert "cursor" not in pi.md_path

    def test_note_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        assert pi.note_path.endswith("-note.md")

    def test_cursor_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        assert pi.cursor_path.endswith("-cursor.md")

    def test_cosma_ids_populated(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        assert set(pi.cosma_ids.keys()) == {"md", "note", "cursor"}

    def test_path_for(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", "cosma")
        assert pi.path_for("md") == pi.md_path
        assert pi.path_for("note") == pi.note_path
        assert pi.path_for("cursor") == pi.cursor_path

    def test_to_triplet(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir), "cosma")
        triplet = pi.to_triplet()
        assert triplet.md.exists is False
        assert triplet.md.path == pi.md_path

    def test_issue_slug(self):
        ref = GitHubRef(org="org", repo="repo", url_type="issues", number=42)
        pi = PathInfo.from_github(ref, "/d", "cosma")
        assert pi.file_prefix == "/d/github-org-repo-issues-42"


# ===================================================================
# PathInfo — Cosma Jira
# ===================================================================


class TestPathInfoCosmaJira:
    def test_file_prefix(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/data", "cosma")
        assert pi.file_prefix == "/data/jira-RUN-3555"

    def test_all_paths(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/d", "cosma")
        assert pi.md_path == "/d/jira-RUN-3555.md"
        assert pi.note_path == "/d/jira-RUN-3555-note.md"
        assert pi.cursor_path == "/d/jira-RUN-3555-cursor.md"

    def test_cosma_ids_populated(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/d", "cosma")
        assert set(pi.cosma_ids.keys()) == {"md", "note", "cursor"}


# ===================================================================
# NoteHeader — Cosma rendering
# ===================================================================


class TestNoteHeaderCosma:
    def _make_header(self, content, ref, kind="md"):
        paths = PathInfo.from_github(ref, "/d", "cosma")
        tags = NoteTags.from_github_ref(ref)
        return NoteHeader.from_content(content, paths, kind, fmt="cosma", tags=tags), paths

    def test_yaml_front_matter_structure(self, sample_note_content, sample_github_ref):
        header, _paths = self._make_header(sample_note_content, sample_github_ref)
        rendered = header.to_string("cosma", "md")
        lines = rendered.split("\n")
        assert lines[0] == "---"
        closing_idx = lines.index("---", 1)
        assert closing_idx > 1

    def test_title_in_front_matter(self, sample_note_content, sample_github_ref):
        header, _ = self._make_header(sample_note_content, sample_github_ref)
        rendered = header.to_string("cosma", "md")
        assert 'title: "Fix container networking regression"' in rendered

    def test_title_with_quotes(self, sample_github_ref):
        content = NoteContent(
            title='Fix "broken" networking',
            url="u",
            source="github",
            status="open",
            author="a",
            created="d",
            description="d",
            note_type="pull_request",
        )
        header, _ = self._make_header(content, sample_github_ref)
        rendered = header.to_string("cosma", "md")
        assert 'title: "Fix \\"broken\\" networking"' in rendered

    def test_id_in_front_matter(self, sample_note_content, sample_github_ref):
        header, paths = self._make_header(sample_note_content, sample_github_ref)
        rendered = header.to_string("cosma", "md")
        assert f"id: {paths.cosma_ids['md']}" in rendered

    def test_type_summary_for_md(self, sample_note_content, sample_github_ref):
        header, _ = self._make_header(sample_note_content, sample_github_ref, "md")
        assert "type: summary" in header.to_string("cosma", "md")

    def test_type_notes_for_note(self, sample_note_content, sample_github_ref):
        header, _ = self._make_header(sample_note_content, sample_github_ref, "note")
        assert "type: notes" in header.to_string("cosma", "note")

    def test_type_analysis_for_cursor(self, sample_note_content, sample_github_ref):
        header, _ = self._make_header(sample_note_content, sample_github_ref, "cursor")
        assert "type: analysis" in header.to_string("cosma", "cursor")

    def test_author_in_front_matter(self, sample_note_content, sample_github_ref):
        header, _ = self._make_header(sample_note_content, sample_github_ref)
        assert "author: developer" in header.to_string("cosma", "md")

    def test_tags_in_front_matter(self, sample_note_content, sample_github_ref):
        header, _ = self._make_header(sample_note_content, sample_github_ref)
        rendered = header.to_string("cosma", "md")
        assert "tags:" in rendered
        assert "- github" in rendered
        assert "- pull_request" in rendered
        assert "- containers/podman" in rendered

    def test_url_after_front_matter(self, sample_note_content, sample_github_ref):
        header, _ = self._make_header(sample_note_content, sample_github_ref)
        rendered = header.to_string("cosma", "md")
        parts = rendered.split("---")
        after_fm = parts[2]
        assert sample_note_content.url in after_fm

    def test_wikilinks_use_cosma_ids(self, sample_note_content, sample_github_ref):
        header, paths = self._make_header(sample_note_content, sample_github_ref, "md")
        assert any(paths.cosma_ids["cursor"] in wl for wl in header.wikilinks)
        assert any(paths.cosma_ids["note"] in wl for wl in header.wikilinks)

    def test_wikilinks_contain_display_text(self, sample_note_content, sample_github_ref):
        header, _ = self._make_header(sample_note_content, sample_github_ref, "md")
        displays = [wl.split("|")[1] for wl in header.wikilinks]
        assert "analysis" in displays
        assert "notes" in displays

    def test_wikilinks_have_typed_prefix(self, sample_note_content, sample_github_ref):
        for kind, expected_types in [
            ("md", ["with_analysis", "with_notes"]),
            ("note", ["with_complementary_analysis", "annotates_summary"]),
            ("cursor", ["analyzes_summary", "with_complementary_notes"]),
        ]:
            header, _ = self._make_header(
                sample_note_content, sample_github_ref, kind,
            )
            prefixes = [wl.split(":")[0] for wl in header.wikilinks]
            assert prefixes == expected_types

    def test_jira_tags(self, sample_jira_content, sample_jira_ref):
        paths = PathInfo.from_jira(sample_jira_ref, "/d", "cosma")
        tags = NoteTags.from_jira_content(sample_jira_content)
        header = NoteHeader.from_content(
            sample_jira_content,
            paths,
            "md",
            fmt="cosma",
            tags=tags,
        )
        rendered = header.to_string("cosma", "md")
        assert "- jira" in rendered
        assert "- issue" in rendered
        assert "containers" not in rendered


# ===================================================================
# NoteBody — Cosma rendering
# ===================================================================


class TestNoteBodyCosma:
    def test_md_body_has_description(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "md")
        rendered = body.to_string("cosma", "md")
        assert "## Description" in rendered
        assert "networking regression" in rendered

    def test_md_body_has_comments(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "md")
        rendered = body.to_string("cosma", "md")
        assert "### @reviewer1 (2024-03-16)" in rendered

    def test_note_body_has_skeleton(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "note")
        rendered = body.to_string("cosma", "note")
        assert "## Notes" in rendered
        assert "## TODOs" in rendered
        assert "## Related" in rendered

    def test_cursor_body_has_skeleton(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "cursor")
        rendered = body.to_string("cosma", "cursor")
        assert "## Analysis" in rendered
        assert "## TODOs" in rendered


class TestNoteBodyCosmaImageStripping:
    """Cosma output must convert ![alt](url) to [alt](url)."""

    def test_images_stripped_from_description(self):
        content = NoteContent(
            source="github",
            title="t",
            url="https://github.com/o/r/issues/1",
            status="open",
            author="a",
            created="2024-01-01",
            description="See ![screenshot](https://example.com/img.png) here",
            comments=[],
        )
        body = NoteBody.from_content(content, "md")
        rendered = body.to_string("cosma", "md")
        assert "![screenshot]" not in rendered
        assert "[screenshot](https://example.com/img.png)" in rendered

    def test_images_stripped_from_comments(self):
        content = NoteContent(
            source="github",
            title="t",
            url="https://github.com/o/r/issues/1",
            status="open",
            author="a",
            created="2024-01-01",
            description="desc",
            comments=[
                Comment(
                    author="u",
                    date="2024-01-02",
                    body="![img](https://example.com/a.jpg)",
                ),
            ],
        )
        body = NoteBody.from_content(content, "md")
        rendered = body.to_string("cosma", "md")
        assert "![img]" not in rendered
        assert "[img](https://example.com/a.jpg)" in rendered

    def test_multiple_images_stripped(self):
        body = NoteBody(
            description="![a](u1) text ![b](u2)",
            comments=[],
            sections=[],
        )
        rendered = body.to_string("cosma", "md")
        assert "![" not in rendered
        assert "[a](u1)" in rendered
        assert "[b](u2)" in rendered

    def test_logseq_preserves_images(self):
        body = NoteBody(
            description="![screenshot](https://example.com/img.png)",
            comments=[],
            sections=[],
        )
        rendered = body.to_string("logseq", "md")
        assert "![screenshot](https://example.com/img.png)" in rendered

    def test_empty_alt_text(self):
        body = NoteBody(
            description="![](https://example.com/img.png)",
            comments=[],
            sections=[],
        )
        rendered = body.to_string("cosma", "md")
        assert "![" not in rendered
        assert "[](https://example.com/img.png)" in rendered
