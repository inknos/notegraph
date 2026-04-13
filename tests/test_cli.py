"""CLI integration tests — end-to-end subcommand behavior."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import notegraph.cli as cli_mod
from notegraph.cli import app
from notegraph.schema import Comment, GitHubRef, NoteContent, PathInfo, TodoItem


def run_cli(*args: str) -> tuple[int, str, str]:
    """Run the CLI app via the meta launcher and capture output.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    cli_mod._cfg = None  # noqa: SLF001

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    exit_code = 0

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            app.meta(list(args), exit_on_error=False)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001
        stderr_buf.write(str(exc))
        exit_code = 1

    return exit_code, stdout_buf.getvalue(), stderr_buf.getvalue()


class TestGitHubCheck:
    def test_check_valid_url(self, tmp_path, sample_config_toml):
        url = "https://github.com/containers/podman/pull/24126"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "Kind" in stdout
        assert "Exists" in stdout
        assert "md" in stdout
        assert "note" in stdout
        assert "cursor" in stdout

    def test_check_issue_url(self, tmp_path, sample_config_toml):
        url = "https://github.com/org/repo/issues/42"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "issues" in stdout

    def test_check_invalid_url(self, sample_config_toml):
        exit_code, _, _stderr = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--check",
            "not-a-url",
        )
        assert exit_code != 0

    def test_check_paths_match_schema(self, tmp_path, sample_config_toml):
        url = "https://github.com/containers/podman/pull/24126"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        ref = GitHubRef.from_url(url)
        cfg_graph_dir = (
            next(
                line
                for line in Path(sample_config_toml).read_text(encoding="utf-8").splitlines()
                if "graph_dir" in line
            )
            .split("=")[1]
            .strip()
            .strip('"')
        )
        pi = PathInfo.from_github(ref, cfg_graph_dir, "logseq")
        assert pi.md_path in stdout
        assert pi.note_path in stdout
        assert pi.cursor_path in stdout

    def test_check_shows_existence_markers(self, tmp_path, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "\u2717" in stdout


class TestJiraCheck:
    def test_check_bare_key(self, tmp_path, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "jira",
            "--check",
            "RUN-3555",
        )
        assert exit_code == 0
        assert "test.atlassian.net___RUN-3555" in stdout

    def test_check_lowercase_key(self, tmp_path, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "jira",
            "--check",
            "run-100",
        )
        assert exit_code == 0
        assert "RUN-100" in stdout


class TestTypeFlag:
    def test_type_logseq(self, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "--type",
            "logseq",
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "logseq_pages" in stdout

    def test_type_cosma_check(self, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "--type",
            "cosma",
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "cosma_data" in stdout
        assert "github-o-r-pull-1" in stdout


class TestDestDirOverride:
    def test_dest_dir_overrides_config(self, tmp_path, sample_config_toml):
        override_dir = str(tmp_path / "custom")
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--check",
            url,
            "--dest-dir",
            override_dir,
        )
        assert exit_code == 0
        assert override_dir in stdout


class TestConfigFlag:
    def test_custom_config_path(self, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "logseq_pages" in stdout

    def test_missing_config_uses_defaults(self, tmp_path):
        missing = str(tmp_path / "nonexistent.toml")
        url = "https://github.com/o/r/pull/1"
        exit_code, _stdout, _ = run_cli(
            "--config",
            missing,
            "github",
            "--check",
            url,
        )
        assert exit_code == 0

    def test_cli_type_overrides_toml(self, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "--type",
            "cosma",
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "cosma_data" in stdout


# ---------------------------------------------------------------------------
# Shared mock content
# ---------------------------------------------------------------------------

_MOCK_GH_CONTENT = NoteContent(
    title="Test PR",
    url="https://github.com/o/r/pull/1",
    source="github",
    status="open",
    author="dev",
    created="2024-01-01",
    description="A test PR.",
    comments=[Comment(author="rev", date="2024-01-02", body="Nice.")],
    note_type="pull_request",
)


# ---------------------------------------------------------------------------
# GitHub fetch+write (end-to-end with mocked fetcher)
# ---------------------------------------------------------------------------


class TestGitHubFetchWrite:
    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_writes_files(self, mock_fetch, sample_config_toml, tmp_path):
        cfg_text = Path(sample_config_toml).read_text(encoding="utf-8")
        graph_dir = (
            next(line for line in cfg_text.splitlines() if "graph_dir" in line)
            .split("=")[1]
            .strip()
            .strip('"')
        )

        url = "https://github.com/o/r/pull/1"
        exit_code, _stdout, _stderr = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            url,
        )
        assert exit_code == 0
        mock_fetch.assert_called_once()

        md = Path(graph_dir) / "github.com___o___r___pull___1.md"
        note = Path(graph_dir) / "github.com___o___r___pull___1___note.md"
        cursor = Path(graph_dir) / "github.com___o___r___pull___1___cursor.md"
        assert md.is_file()
        assert note.is_file()
        assert cursor.is_file()

        md_text = md.read_text(encoding="utf-8")
        assert "Test PR" in md_text
        assert "A test PR." in md_text

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_cosma_write(self, mock_fetch, sample_config_toml, tmp_path):
        cfg_text = Path(sample_config_toml).read_text(encoding="utf-8")
        cosma_dir = (
            next(line for line in cfg_text.splitlines() if "data_dir" in line)
            .split("=")[1]
            .strip()
            .strip('"')
        )

        url = "https://github.com/o/r/pull/1"
        exit_code, _stdout, _stderr = run_cli(
            "--config",
            str(sample_config_toml),
            "--type",
            "cosma",
            "github",
            url,
        )
        assert exit_code == 0

        md = Path(cosma_dir) / "github-o-r-pull-1.md"
        note = Path(cosma_dir) / "github-o-r-pull-1-note.md"
        cursor = Path(cosma_dir) / "github-o-r-pull-1-cursor.md"
        assert md.is_file()
        assert note.is_file()
        assert cursor.is_file()

        md_text = md.read_text(encoding="utf-8")
        assert "---" in md_text
        assert "title:" in md_text


# ---------------------------------------------------------------------------
# --summary / --note / --analysis kind selection
# ---------------------------------------------------------------------------


class TestKindFlags:
    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_summary_only(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--summary",
            url,
        )
        assert exit_code == 0
        assert (Path(graph_dir) / "github.com___o___r___pull___1.md").is_file()
        assert not (Path(graph_dir) / "github.com___o___r___pull___1___note.md").is_file()
        assert not (Path(graph_dir) / "github.com___o___r___pull___1___cursor.md").is_file()

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_note_and_analysis(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--note",
            "--analysis",
            url,
        )
        assert exit_code == 0
        assert not (Path(graph_dir) / "github.com___o___r___pull___1.md").is_file()
        assert (Path(graph_dir) / "github.com___o___r___pull___1___note.md").is_file()
        assert (Path(graph_dir) / "github.com___o___r___pull___1___cursor.md").is_file()

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_no_flags_generates_all(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            url,
        )
        assert exit_code == 0
        assert (Path(graph_dir) / "github.com___o___r___pull___1.md").is_file()
        assert (Path(graph_dir) / "github.com___o___r___pull___1___note.md").is_file()
        assert (Path(graph_dir) / "github.com___o___r___pull___1___cursor.md").is_file()


# ---------------------------------------------------------------------------
# --replace flag
# ---------------------------------------------------------------------------


class TestReplaceFlag:
    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_replace_overwrites_note(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        note_path = Path(graph_dir) / "github.com___o___r___pull___1___note.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("MY NOTES", encoding="utf-8")

        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--replace",
            "--note",
            url,
        )
        assert exit_code == 0
        assert note_path.read_text(encoding="utf-8") != "MY NOTES"

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_no_replace_preserves_note(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        note_path = Path(graph_dir) / "github.com___o___r___pull___1___note.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("MY NOTES", encoding="utf-8")

        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            url,
        )
        assert exit_code == 0
        assert note_path.read_text(encoding="utf-8") == "MY NOTES"

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_replace_summary_only(self, mock_fetch, sample_config_toml, tmp_path):
        """--replace --summary: note/cursor files are untouched."""
        graph_dir = _extract_graph_dir(sample_config_toml)
        note_path = Path(graph_dir) / "github.com___o___r___pull___1___note.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("MY NOTES", encoding="utf-8")

        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--replace",
            "--summary",
            url,
        )
        assert exit_code == 0
        assert note_path.read_text(encoding="utf-8") == "MY NOTES"


# ---------------------------------------------------------------------------
# --json flag
# ---------------------------------------------------------------------------


class TestJsonFlag:
    def test_json_check(self, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--check",
            "--json",
            url,
        )
        assert exit_code == 0
        data = json.loads(stdout)
        assert "md" in data
        assert "note" in data
        assert "cursor" in data
        assert "path" in data["md"]
        assert "exists" in data["md"]

    def test_json_check_jira(self, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "jira",
            "--check",
            "--json",
            "RUN-3555",
        )
        assert exit_code == 0
        data = json.loads(stdout)
        assert "RUN-3555" in data["md"]["path"]

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_json_render_no_files(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--json",
            url,
        )
        assert exit_code == 0

        data = json.loads(stdout)
        assert "md" in data
        assert "note" in data
        assert "cursor" in data
        assert "path" in data["md"]
        assert "content" in data["md"]
        assert "Test PR" in data["md"]["content"]

        assert not (Path(graph_dir) / "github.com___o___r___pull___1.md").is_file()

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_json_with_kind_filter(self, mock_fetch, sample_config_toml, tmp_path):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--json",
            "--summary",
            url,
        )
        assert exit_code == 0

        data = json.loads(stdout)
        assert "md" in data
        assert "note" not in data
        assert "cursor" not in data

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_json_cosma_render(self, mock_fetch, sample_config_toml, tmp_path):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "--type",
            "cosma",
            "github",
            "--json",
            url,
        )
        assert exit_code == 0

        data = json.loads(stdout)
        assert "---" in data["md"]["content"]
        assert "type: summary" in data["md"]["content"]


# ---------------------------------------------------------------------------
# Jira fetch+write (still raises NotImplementedError)
# ---------------------------------------------------------------------------


class TestJiraFetchWrite:
    def test_jira_write_not_implemented(self, sample_config_toml):
        exit_code, _stdout, stderr = run_cli(
            "--config",
            str(sample_config_toml),
            "jira",
            "RUN-100",
        )
        assert exit_code != 0
        assert "not yet implemented" in stderr


# ---------------------------------------------------------------------------
# --todo flag
# ---------------------------------------------------------------------------

_MOCK_TODO_ITEMS = [
    TodoItem(
        url="https://github.com/o/r/pull/1",
        title="Fix bug",
        source="github",
        kind="pull_request",
        state="open",
        repo="o/r",
        updated_at="2026-04-12",
    ),
    TodoItem(
        url="https://github.com/o/r/issues/2",
        title="Feature request",
        source="github",
        kind="issue",
        state="open",
        repo="o/r",
        updated_at="2026-04-10",
    ),
]


class TestTodoFlag:
    @patch(
        "notegraph.cli.github_api.fetch_todo",
        return_value=_MOCK_TODO_ITEMS,
    )
    def test_todo_plain_output(self, mock_fetch, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--todo",
            "--org",
            "o",
        )
        assert exit_code == 0
        lines = stdout.strip().splitlines()
        assert len(lines) == 2
        assert lines[0] == "https://github.com/o/r/pull/1"
        assert lines[1] == "https://github.com/o/r/issues/2"

    @patch(
        "notegraph.cli.github_api.fetch_todo",
        return_value=_MOCK_TODO_ITEMS,
    )
    def test_todo_json_output(self, mock_fetch, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--todo",
            "--json",
            "--org",
            "o",
        )
        assert exit_code == 0
        data = json.loads(stdout)
        assert len(data) == 2
        assert data[0]["url"] == "https://github.com/o/r/pull/1"
        assert data[0]["kind"] == "pull_request"
        assert data[0]["source"] == "github"
        assert data[1]["kind"] == "issue"

    def test_todo_no_scope_errors(self, sample_config_toml):
        exit_code, _, stderr = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--todo",
        )
        assert exit_code != 0
        assert "--org or --repo" in stderr

    def test_no_url_no_todo_errors(self, sample_config_toml):
        exit_code, _, stderr = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
        )
        assert exit_code != 0
        assert "URL is required" in stderr

    @patch(
        "notegraph.cli.github_api.fetch_todo",
        return_value=[],
    )
    def test_todo_empty_result(self, mock_fetch, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--todo",
            "--org",
            "emptyorg",
        )
        assert exit_code == 0
        assert stdout.strip() == ""

    @patch(
        "notegraph.cli.github_api.fetch_todo",
        return_value=_MOCK_TODO_ITEMS,
    )
    def test_todo_with_repo(self, mock_fetch, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--todo",
            "--repo",
            "o/r",
        )
        assert exit_code == 0
        assert len(stdout.strip().splitlines()) == 2
        mock_fetch.assert_called_once()
        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["repos"] == ["o/r"]

    @patch(
        "notegraph.cli.github_api.fetch_todo",
        return_value=_MOCK_TODO_ITEMS,
    )
    def test_todo_combined_org_repo(self, mock_fetch, sample_config_toml):
        exit_code, _stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "github",
            "--todo",
            "--org",
            "containers",
            "--repo",
            "o/r",
        )
        assert exit_code == 0
        mock_fetch.assert_called_once()
        call_kwargs = mock_fetch.call_args[1]
        assert call_kwargs["orgs"] == ["containers"]
        assert call_kwargs["repos"] == ["o/r"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_graph_dir(config_path: Path) -> str:
    """Read the graph_dir value from a test config TOML."""
    cfg_text = Path(config_path).read_text(encoding="utf-8")
    return (
        next(line for line in cfg_text.splitlines() if "graph_dir" in line)
        .split("=")[1]
        .strip()
        .strip('"')
    )
