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
    expand_hash_refs,
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
            agent=FileStatus(path="/p/foo___agent.md", exists=True),
        )
        dumped = triplet.model_dump()
        assert dumped == {
            "md": {"path": "/p/foo.md", "exists": True},
            "note": {"path": "/p/foo___note.md", "exists": False},
            "agent": {"path": "/p/foo___agent.md", "exists": True},
        }

    def test_model_dump_json_is_valid(self):
        triplet = NoteTriplet(
            md=FileStatus(path="/a.md", exists=False),
            note=FileStatus(path="/a___note.md", exists=False),
            agent=FileStatus(path="/a___agent.md", exists=False),
        )
        parsed = json.loads(triplet.model_dump_json())
        assert parsed["md"]["exists"] is False

    def test_format_table_contains_all_kinds(self):
        triplet = NoteTriplet(
            md=FileStatus(path="/p/foo.md", exists=True),
            note=FileStatus(path="/p/foo___note.md", exists=False),
            agent=FileStatus(path="/p/foo___agent.md", exists=True),
        )
        table = triplet.format_table()
        assert "Kind" in table
        assert "Exists" in table
        assert "Path" in table
        assert "md" in table
        assert "note" in table
        assert "agent" in table

    def test_format_table_check_mark_for_exists(self):
        triplet = NoteTriplet(
            md=FileStatus(path="/p/foo.md", exists=True),
            note=FileStatus(path="/p/foo___note.md", exists=False),
            agent=FileStatus(path="/p/foo___agent.md", exists=False),
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
            agent=FileStatus(path="/some/dir/file___agent.md", exists=False),
        )
        table = triplet.format_table()
        assert "/some/dir/file.md" in table
        assert "/some/dir/file___note.md" in table
        assert "/some/dir/file___agent.md" in table


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

    def test_derived_agent_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d")
        assert pi.agent_path == "/d/github.com___containers___podman___pull___24126___agent.md"

    def test_wikilinks(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d")
        assert pi.wikilink == "github.com/containers/podman/pull/24126"
        assert pi.wikilink_note == "github.com/containers/podman/pull/24126/note"
        assert pi.wikilink_agent == "github.com/containers/podman/pull/24126/agent"

    def test_path_for(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d")
        assert pi.path_for("md") == pi.md_path
        assert pi.path_for("note") == pi.note_path
        assert pi.path_for("agent") == pi.agent_path

    def test_prefix_file_prefix(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", prefix="Wiki___Items___")
        assert pi.file_prefix == "/d/Wiki___Items___github.com___containers___podman___pull___24126"

    def test_prefix_md_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", prefix="Wiki___Items___")
        assert pi.md_path == "/d/Wiki___Items___github.com___containers___podman___pull___24126.md"

    def test_prefix_note_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", prefix="Wiki___Items___")
        assert pi.note_path == "/d/Wiki___Items___github.com___containers___podman___pull___24126___note.md"

    def test_prefix_agent_path(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", prefix="Wiki___Items___")
        assert pi.agent_path == "/d/Wiki___Items___github.com___containers___podman___pull___24126___agent.md"

    def test_prefix_wikilinks(self, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, "/d", prefix="Wiki___Items___")
        assert pi.wikilink == "Wiki/Items/github.com/containers/podman/pull/24126"
        assert pi.wikilink_note == "Wiki/Items/github.com/containers/podman/pull/24126/note"
        assert pi.wikilink_agent == "Wiki/Items/github.com/containers/podman/pull/24126/agent"

    def test_empty_prefix_unchanged(self, sample_github_ref):
        pi_no_prefix = PathInfo.from_github(sample_github_ref, "/d")
        pi_empty = PathInfo.from_github(sample_github_ref, "/d", prefix="")
        assert pi_no_prefix.file_prefix == pi_empty.file_prefix
        assert pi_no_prefix.wikilink_prefix == pi_empty.wikilink_prefix


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
        assert pi.wikilink_agent == "test.atlassian.net/RUN-3555/agent"

    def test_md_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest")
        assert pi.md_path == "/dest/test.atlassian.net___RUN-3555.md"

    def test_note_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest")
        assert pi.note_path == "/dest/test.atlassian.net___RUN-3555___note.md"

    def test_agent_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest")
        assert pi.agent_path == "/dest/test.atlassian.net___RUN-3555___agent.md"

    def test_prefix_file_prefix(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest", prefix="Wiki___Items___")
        assert pi.file_prefix == "/dest/Wiki___Items___test.atlassian.net___RUN-3555"

    def test_prefix_md_path(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest", prefix="Wiki___Items___")
        assert pi.md_path == "/dest/Wiki___Items___test.atlassian.net___RUN-3555.md"

    def test_prefix_wikilinks(self, sample_jira_ref):
        pi = PathInfo.from_jira(sample_jira_ref, "/dest", prefix="Wiki___Items___")
        assert pi.wikilink == "Wiki/Items/test.atlassian.net/RUN-3555"
        assert pi.wikilink_note == "Wiki/Items/test.atlassian.net/RUN-3555/note"
        assert pi.wikilink_agent == "Wiki/Items/test.atlassian.net/RUN-3555/agent"


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

    def test_prefix_forwarded_github(self, sample_github_ref):
        pi = PathInfo.from_ref(sample_github_ref, "/d", prefix="P___")
        assert pi.file_prefix.startswith("/d/P___")
        assert pi.wikilink_prefix.startswith("P/")

    def test_prefix_forwarded_jira(self, sample_jira_ref):
        pi = PathInfo.from_ref(sample_jira_ref, "/d", prefix="P___")
        assert pi.file_prefix.startswith("/d/P___")
        assert pi.wikilink_prefix.startswith("P/")


# ===================================================================
# PathInfo.to_triplet — file existence
# ===================================================================


class TestPathInfoToTriplet:
    def test_no_files_exist(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        triplet = pi.to_triplet()
        assert triplet.md.exists is False
        assert triplet.note.exists is False
        assert triplet.agent.exists is False

    def test_all_files_exist(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        for path in (pi.md_path, pi.note_path, pi.agent_path):
            Path(path).write_text("content", encoding="utf-8")

        triplet = pi.to_triplet()
        assert triplet.md.exists is True
        assert triplet.note.exists is True
        assert triplet.agent.exists is True

    def test_partial_existence(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.md_path).write_text("x", encoding="utf-8")

        triplet = pi.to_triplet()
        assert triplet.md.exists is True
        assert triplet.note.exists is False
        assert triplet.agent.exists is False

    def test_paths_in_triplet_match(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        triplet = pi.to_triplet()
        assert triplet.md.path == pi.md_path
        assert triplet.note.path == pi.note_path
        assert triplet.agent.path == pi.agent_path


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
        assert "agent" in header.wikilinks[0]
        assert "note" in header.wikilinks[1]

    def test_from_content_note(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "note")
        assert "agent" in header.wikilinks[0]
        assert header.wikilinks[1] == paths.wikilink

    def test_from_content_agent(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "agent")
        assert header.wikilinks[0] == paths.wikilink
        assert "note" in header.wikilinks[1]

    def test_to_string_agent(self, sample_note_content, sample_github_ref):
        paths = PathInfo.from_github(sample_github_ref, "/d")
        header = NoteHeader.from_content(sample_note_content, paths, "agent")
        rendered = header.to_string("agent")
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

    def test_from_content_agent(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "agent")
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

    def test_to_string_agent(self, sample_note_content):
        body = NoteBody.from_content(sample_note_content, "agent")
        rendered = body.to_string("agent")
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


# ===================================================================
# expand_hash_refs
# ===================================================================


class TestExpandHashRefs:
    def test_bare_ref_replaced(self):
        result = expand_hash_refs("See #1234 for details", "containers", "podman")
        assert result == "See [[github.com/containers/podman/issues/1234]] for details"

    def test_multiple_refs(self):
        result = expand_hash_refs("Fixes #10 and #20", "myorg", "myrepo")
        assert result == (
            "Fixes [[github.com/myorg/myrepo/issues/10]] and [[github.com/myorg/myrepo/issues/20]]"
        )

    def test_already_linked_not_doubled(self):
        text = "See [[github.com/o/r/issues/5]] already"
        assert expand_hash_refs(text, "o", "r") == text

    def test_html_entity_not_touched(self):
        result = expand_hash_refs("char &#123; here", "o", "r")
        assert result == "char &#123; here"

    def test_ref_at_start_of_line(self):
        result = expand_hash_refs("#99 is the issue", "a", "b")
        assert result == "[[github.com/a/b/issues/99]] is the issue"

    def test_no_digits_after_hash(self):
        text = "use # for comments"
        assert expand_hash_refs(text, "o", "r") == text

    def test_empty_string(self):
        assert expand_hash_refs("", "o", "r") == ""

    def test_no_refs_unchanged(self):
        text = "Just a normal sentence."
        assert expand_hash_refs(text, "o", "r") == text
