"""Tests for the writer orchestrator."""

from __future__ import annotations

from pathlib import Path

from notegraph.schema import PathInfo, RenderedNote
from notegraph.writer import check, render, write


class TestCheck:
    def test_github_no_files(self, tmp_dest_dir, sample_github_ref):
        triplet = check(sample_github_ref, str(tmp_dest_dir))
        assert triplet.md.exists is False
        assert triplet.note.exists is False
        assert triplet.cursor.exists is False

    def test_github_with_existing_files(self, tmp_dest_dir, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.md_path).write_text("x", encoding="utf-8")
        Path(pi.note_path).write_text("x", encoding="utf-8")

        triplet = check(sample_github_ref, str(tmp_dest_dir))
        assert triplet.md.exists is True
        assert triplet.note.exists is True
        assert triplet.cursor.exists is False

    def test_jira(self, tmp_dest_dir, sample_jira_ref):
        triplet = check(sample_jira_ref, str(tmp_dest_dir))
        assert triplet.md.exists is False
        assert "test.atlassian.net___RUN-3555" in triplet.md.path

    def test_paths_are_absolute(self, tmp_dest_dir, sample_github_ref):
        triplet = check(sample_github_ref, str(tmp_dest_dir))
        assert Path(triplet.md.path).is_absolute()


class TestWriteFullTriplet:
    def test_creates_all_files(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        assert Path(pi.md_path).is_file()
        assert Path(pi.note_path).is_file()
        assert Path(pi.cursor_path).is_file()

    def test_md_contains_description(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        md_text = Path(pi.md_path).read_text(encoding="utf-8")
        assert "## Description" in md_text
        assert "networking regression" in md_text

    def test_md_contains_comments(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        md_text = Path(pi.md_path).read_text(encoding="utf-8")
        assert "### @reviewer1 (2024-03-16)" in md_text
        assert "LGTM" in md_text

    def test_md_contains_wikilinks(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        md_text = Path(pi.md_path).read_text(encoding="utf-8")
        assert "[[github.com/containers/podman/pull/24126/cursor]]" in md_text
        assert "[[github.com/containers/podman/pull/24126/note]]" in md_text

    def test_note_contains_skeleton(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        note_text = Path(pi.note_path).read_text(encoding="utf-8")
        assert "## Notes" in note_text
        assert "## TODOs" in note_text
        assert "## Related" in note_text

    def test_cursor_contains_metadata(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        cursor_text = Path(pi.cursor_path).read_text(encoding="utf-8")
        assert "## Analysis" in cursor_text
        assert "## TODOs" in cursor_text
        assert "**Type:** pull_request" in cursor_text

    def test_creates_dest_dir_if_missing(self, tmp_path, sample_note_content, sample_github_ref):
        dest = str(tmp_path / "nonexistent" / "dir")
        write(sample_note_content, sample_github_ref, dest)

        pi = PathInfo.from_github(sample_github_ref, dest)
        assert Path(pi.md_path).is_file()


class TestWriteKinds:
    def test_summary_only(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        write(
            sample_note_content,
            sample_github_ref,
            str(tmp_dest_dir),
            kinds=("md",),
        )

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        assert Path(pi.md_path).is_file()
        assert not Path(pi.note_path).is_file()
        assert not Path(pi.cursor_path).is_file()

    def test_note_and_analysis(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        write(
            sample_note_content,
            sample_github_ref,
            str(tmp_dest_dir),
            kinds=("note", "cursor"),
        )

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        assert not Path(pi.md_path).is_file()
        assert Path(pi.note_path).is_file()
        assert Path(pi.cursor_path).is_file()

    def test_single_analysis(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        write(
            sample_note_content,
            sample_github_ref,
            str(tmp_dest_dir),
            kinds=("cursor",),
        )

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        assert not Path(pi.md_path).is_file()
        assert not Path(pi.note_path).is_file()
        assert Path(pi.cursor_path).is_file()


class TestWriteSkipIfExists:
    def test_note_not_overwritten(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.note_path).write_text("USER NOTES", encoding="utf-8")

        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        assert Path(pi.note_path).read_text(encoding="utf-8") == "USER NOTES"

    def test_cursor_not_overwritten(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.cursor_path).write_text("CURSOR ANALYSIS", encoding="utf-8")

        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        assert Path(pi.cursor_path).read_text(encoding="utf-8") == "CURSOR ANALYSIS"

    def test_md_always_overwritten(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.md_path).write_text("OLD CONTENT", encoding="utf-8")

        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        new_text = Path(pi.md_path).read_text(encoding="utf-8")
        assert new_text != "OLD CONTENT"
        assert "## Description" in new_text


class TestWriteReplace:
    def test_note_overwritten_with_replace(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.note_path).write_text("USER NOTES", encoding="utf-8")

        write(sample_note_content, sample_github_ref, str(tmp_dest_dir), replace=True)

        assert Path(pi.note_path).read_text(encoding="utf-8") != "USER NOTES"

    def test_cursor_overwritten_with_replace(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.cursor_path).write_text("CURSOR ANALYSIS", encoding="utf-8")

        write(sample_note_content, sample_github_ref, str(tmp_dest_dir), replace=True)

        assert Path(pi.cursor_path).read_text(encoding="utf-8") != "CURSOR ANALYSIS"

    def test_replace_with_kinds(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        """Only the selected kinds are written, even with replace=True."""
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.cursor_path).write_text("CURSOR ANALYSIS", encoding="utf-8")

        write(
            sample_note_content,
            sample_github_ref,
            str(tmp_dest_dir),
            kinds=("md",),
            replace=True,
        )

        assert Path(pi.cursor_path).read_text(encoding="utf-8") == "CURSOR ANALYSIS"

    def test_replace_false_default(self, tmp_dest_dir, sample_note_content, sample_github_ref):
        """Sanity check: default replace=False preserves existing files."""
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        Path(pi.note_path).write_text("USER NOTES", encoding="utf-8")

        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        assert Path(pi.note_path).read_text(encoding="utf-8") == "USER NOTES"


class TestWriteJira:
    def test_creates_jira_files(self, tmp_dest_dir, sample_jira_content, sample_jira_ref):
        write(sample_jira_content, sample_jira_ref, str(tmp_dest_dir))

        pi = PathInfo.from_jira(sample_jira_ref, str(tmp_dest_dir))
        assert Path(pi.md_path).is_file()
        assert Path(pi.note_path).is_file()
        assert Path(pi.cursor_path).is_file()

    def test_jira_md_contains_content(self, tmp_dest_dir, sample_jira_content, sample_jira_ref):
        write(sample_jira_content, sample_jira_ref, str(tmp_dest_dir))

        pi = PathInfo.from_jira(sample_jira_ref, str(tmp_dest_dir))
        md_text = Path(pi.md_path).read_text(encoding="utf-8")
        assert "Implement retry logic" in md_text
        assert "## Description" in md_text

    def test_jira_wikilinks(self, tmp_dest_dir, sample_jira_content, sample_jira_ref):
        write(sample_jira_content, sample_jira_ref, str(tmp_dest_dir))

        pi = PathInfo.from_jira(sample_jira_ref, str(tmp_dest_dir))
        md_text = Path(pi.md_path).read_text(encoding="utf-8")
        assert "[[test.atlassian.net/RUN-3555/cursor]]" in md_text
        assert "[[test.atlassian.net/RUN-3555/note]]" in md_text


# ---------------------------------------------------------------------------
# render() — returns content without writing
# ---------------------------------------------------------------------------


class TestRender:
    def test_returns_all_kinds_by_default(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        result = render(sample_note_content, sample_github_ref, str(tmp_dest_dir))
        assert set(result.keys()) == {"md", "note", "cursor"}

    def test_returns_rendered_note_instances(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        result = render(sample_note_content, sample_github_ref, str(tmp_dest_dir))
        for note in result.values():
            assert isinstance(note, RenderedNote)
            assert note.path
            assert note.content

    def test_respects_kinds_filter(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        result = render(
            sample_note_content,
            sample_github_ref,
            str(tmp_dest_dir),
            kinds=("md", "cursor"),
        )
        assert set(result.keys()) == {"md", "cursor"}

    def test_single_kind(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        result = render(
            sample_note_content,
            sample_github_ref,
            str(tmp_dest_dir),
            kinds=("note",),
        )
        assert set(result.keys()) == {"note"}
        assert "## Notes" in result["note"].content

    def test_does_not_write_files(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        render(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        assert not Path(pi.md_path).is_file()
        assert not Path(pi.note_path).is_file()
        assert not Path(pi.cursor_path).is_file()

    def test_md_content_matches_written(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        result = render(sample_note_content, sample_github_ref, str(tmp_dest_dir))
        write(sample_note_content, sample_github_ref, str(tmp_dest_dir))

        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        written = Path(pi.md_path).read_text(encoding="utf-8")
        assert written == result["md"].content + "\n"

    def test_paths_match_pathinfo(
        self,
        tmp_dest_dir,
        sample_note_content,
        sample_github_ref,
    ):
        result = render(sample_note_content, sample_github_ref, str(tmp_dest_dir))
        pi = PathInfo.from_github(sample_github_ref, str(tmp_dest_dir))
        assert result["md"].path == pi.md_path
        assert result["note"].path == pi.note_path
        assert result["cursor"].path == pi.cursor_path


class TestRenderedNoteModel:
    def test_basic(self, tmp_path):
        p = str(tmp_path / "test.md")
        rn = RenderedNote(path=p, content="# Hello")
        assert rn.path == p
        assert rn.content == "# Hello"

    def test_model_dump(self, tmp_path):
        p = str(tmp_path / "test.md")
        rn = RenderedNote(path=p, content="# Hello")
        d = rn.model_dump()
        assert d == {"path": p, "content": "# Hello"}

    def test_model_dump_json(self, tmp_path):
        p = str(tmp_path / "test.md")
        rn = RenderedNote(path=p, content="# Hello")
        j = rn.model_dump_json()
        assert '"path"' in j
        assert '"content"' in j
