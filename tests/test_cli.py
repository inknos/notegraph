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


# ---------------------------------------------------------------------------
# fetch --source github --check
# ---------------------------------------------------------------------------


class TestFetchGitHubCheck:
    def test_check_valid_url(self, tmp_path, sample_config_toml):
        url = "https://github.com/containers/podman/pull/24126"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "Kind" in stdout
        assert "Exists" in stdout
        assert "md" in stdout
        assert "note" in stdout
        assert "agent" in stdout

    def test_check_issue_url(self, tmp_path, sample_config_toml):
        url = "https://github.com/org/repo/issues/42"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
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
            "fetch",
            "--source",
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
            "fetch",
            "--source",
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        ref = GitHubRef.from_url(url)
        cfg_graph_dir = _extract_graph_dir(sample_config_toml)
        pi = PathInfo.from_github(ref, cfg_graph_dir)
        assert pi.md_path in stdout
        assert pi.note_path in stdout
        assert pi.agent_path in stdout

    def test_check_shows_existence_markers(self, tmp_path, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            "--check",
            url,
        )
        assert exit_code == 0
        assert "\u2717" in stdout


# ---------------------------------------------------------------------------
# fetch --source jira --check
# ---------------------------------------------------------------------------


class TestFetchJiraCheck:
    def test_check_bare_key(self, tmp_path, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
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
            "fetch",
            "--source",
            "jira",
            "--check",
            "run-100",
        )
        assert exit_code == 0
        assert "RUN-100" in stdout


# ---------------------------------------------------------------------------
# fetch --dest-dir
# ---------------------------------------------------------------------------


class TestFetchDestDirOverride:
    def test_dest_dir_overrides_config(self, tmp_path, sample_config_toml):
        override_dir = str(tmp_path / "custom")
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            "--check",
            url,
            "--dest-dir",
            override_dir,
        )
        assert exit_code == 0
        assert override_dir in stdout


# ---------------------------------------------------------------------------
# Global --config flag
# ---------------------------------------------------------------------------


class TestConfigFlag:
    def test_custom_config_path(self, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
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
            "fetch",
            "--source",
            "github",
            "--check",
            url,
        )
        assert exit_code == 0


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
# fetch --source github (end-to-end with mocked fetcher)
# ---------------------------------------------------------------------------


class TestFetchGitHubWrite:
    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_writes_files(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)

        url = "https://github.com/o/r/pull/1"
        exit_code, _stdout, _stderr = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            url,
        )
        assert exit_code == 0
        mock_fetch.assert_called_once()

        md = Path(graph_dir) / "github.com___o___r___pull___1.md"
        note = Path(graph_dir) / "github.com___o___r___pull___1___note.md"
        agent = Path(graph_dir) / "github.com___o___r___pull___1___agent.md"
        assert md.is_file()
        assert note.is_file()
        assert agent.is_file()

        md_text = md.read_text(encoding="utf-8")
        assert "Test PR" in md_text
        assert "A test PR." in md_text


# ---------------------------------------------------------------------------
# fetch --summary / --note / --analysis kind selection
# ---------------------------------------------------------------------------


class TestFetchKindFlags:
    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_summary_only(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            "--summary",
            url,
        )
        assert exit_code == 0
        assert (Path(graph_dir) / "github.com___o___r___pull___1.md").is_file()
        assert not (Path(graph_dir) / "github.com___o___r___pull___1___note.md").is_file()
        assert not (Path(graph_dir) / "github.com___o___r___pull___1___agent.md").is_file()

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_note_and_analysis(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            "--note",
            "--analysis",
            url,
        )
        assert exit_code == 0
        assert not (Path(graph_dir) / "github.com___o___r___pull___1.md").is_file()
        assert (Path(graph_dir) / "github.com___o___r___pull___1___note.md").is_file()
        assert (Path(graph_dir) / "github.com___o___r___pull___1___agent.md").is_file()

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_no_flags_generates_all(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            url,
        )
        assert exit_code == 0
        assert (Path(graph_dir) / "github.com___o___r___pull___1.md").is_file()
        assert (Path(graph_dir) / "github.com___o___r___pull___1___note.md").is_file()
        assert (Path(graph_dir) / "github.com___o___r___pull___1___agent.md").is_file()


# ---------------------------------------------------------------------------
# fetch --replace flag
# ---------------------------------------------------------------------------


class TestFetchReplaceFlag:
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
            "fetch",
            "--source",
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
            "fetch",
            "--source",
            "github",
            url,
        )
        assert exit_code == 0
        assert note_path.read_text(encoding="utf-8") == "MY NOTES"

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    def test_replace_summary_only(self, mock_fetch, sample_config_toml, tmp_path):
        """--replace --summary: note/agent files are untouched."""
        graph_dir = _extract_graph_dir(sample_config_toml)
        note_path = Path(graph_dir) / "github.com___o___r___pull___1___note.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("MY NOTES", encoding="utf-8")

        url = "https://github.com/o/r/pull/1"
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            "--replace",
            "--summary",
            url,
        )
        assert exit_code == 0
        assert note_path.read_text(encoding="utf-8") == "MY NOTES"


# ---------------------------------------------------------------------------
# fetch --json flag
# ---------------------------------------------------------------------------


class TestFetchJsonFlag:
    def test_json_check(self, sample_config_toml):
        url = "https://github.com/o/r/pull/1"
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
            "--check",
            "--json",
            url,
        )
        assert exit_code == 0
        data = json.loads(stdout)
        assert "md" in data
        assert "note" in data
        assert "agent" in data
        assert "path" in data["md"]
        assert "exists" in data["md"]

    def test_json_check_jira(self, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
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
            "fetch",
            "--source",
            "github",
            "--json",
            url,
        )
        assert exit_code == 0

        data = json.loads(stdout)
        assert "md" in data
        assert "note" in data
        assert "agent" in data
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
            "fetch",
            "--source",
            "github",
            "--json",
            "--summary",
            url,
        )
        assert exit_code == 0

        data = json.loads(stdout)
        assert "md" in data
        assert "note" not in data
        assert "agent" not in data


# ---------------------------------------------------------------------------
# fetch --source jira (write)
# ---------------------------------------------------------------------------

_MOCK_JIRA_CONTENT = NoteContent(
    title="Implement retry logic",
    url="https://test.atlassian.net/browse/RUN-100",
    source="jira",
    status="In Progress",
    author="Ada Lovelace",
    created="2024-01-10",
    description="Add retry logic.",
    comments=[Comment(author="PM User", date="2024-01-12", body="Priority raised.")],
    note_type="story",
    extra={"assignee": "Ada Lovelace", "issue_type": "Story"},
)

_MOCK_JIRA_CONTENT_WITH_GH = NoteContent(
    title="Implement retry logic",
    url="https://test.atlassian.net/browse/RUN-100",
    source="jira",
    status="In Progress",
    author="Ada Lovelace",
    created="2024-01-10",
    description="Add retry logic.",
    comments=[],
    note_type="story",
    extra={
        "assignee": "Ada Lovelace",
        "issue_type": "Story",
        "github_url": "https://github.com/acme/widgets/pull/123",
    },
)


class TestFetchJiraWrite:
    @patch("notegraph.cli.jira_api.fetch", return_value=_MOCK_JIRA_CONTENT)
    def test_writes_jira_files(self, mock_fetch, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "jira",
            "RUN-100",
        )
        assert exit_code == 0
        mock_fetch.assert_called_once()

        md = Path(graph_dir) / "test.atlassian.net___RUN-100.md"
        note = Path(graph_dir) / "test.atlassian.net___RUN-100___note.md"
        agent = Path(graph_dir) / "test.atlassian.net___RUN-100___agent.md"
        assert md.is_file()
        assert note.is_file()
        assert agent.is_file()
        assert "Implement retry logic" in md.read_text(encoding="utf-8")

    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    @patch("notegraph.cli.jira_api.fetch", return_value=_MOCK_JIRA_CONTENT_WITH_GH)
    def test_chains_github(self, mock_jira, mock_gh, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "jira",
            "RUN-100",
        )
        assert exit_code == 0
        mock_jira.assert_called_once()
        mock_gh.assert_called_once()

        jira_md = Path(graph_dir) / "test.atlassian.net___RUN-100.md"
        gh_md = Path(graph_dir) / "github.com___acme___widgets___pull___123.md"
        assert jira_md.is_file()
        assert gh_md.is_file()

    @patch("notegraph.cli.jira_api.fetch", return_value=_MOCK_JIRA_CONTENT)
    def test_no_chain_without_github_url(self, mock_jira, sample_config_toml, tmp_path):
        graph_dir = _extract_graph_dir(sample_config_toml)
        exit_code, _, _ = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "jira",
            "RUN-100",
        )
        assert exit_code == 0

        gh_files = list(Path(graph_dir).glob("github.com*"))
        assert gh_files == []


# ---------------------------------------------------------------------------
# fetch: missing target errors
# ---------------------------------------------------------------------------


class TestFetchErrors:
    def test_missing_target(self, sample_config_toml):
        exit_code, _, _stderr = run_cli(
            "--config",
            str(sample_config_toml),
            "fetch",
            "--source",
            "github",
        )
        assert exit_code != 0


# ---------------------------------------------------------------------------
# ``todo`` subcommand
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

_MOCK_JIRA_TODO_ITEMS = [
    TodoItem(
        url="https://test.atlassian.net/browse/RUN-100",
        title="Fix the widget",
        source="jira",
        kind="bug",
        state="In Progress",
        repo="RUN",
        updated_at="2026-04-10",
    ),
    TodoItem(
        url="https://test.atlassian.net/browse/RUN-50",
        title="Add caching",
        source="jira",
        kind="story",
        state="Open",
        repo="RUN",
        updated_at="2026-04-08",
    ),
]


class TestTodoGitHub:
    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_plain_output(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[github]\norgs = ["o"]\n',
            encoding="utf-8",
        )
        exit_code, stdout, _ = run_cli(
            "--config", str(config), "todo", "--source", "github",
        )
        assert exit_code == 0
        lines = stdout.strip().splitlines()
        assert len(lines) == 2
        assert lines[0] == "https://github.com/o/r/pull/1"
        assert lines[1] == "https://github.com/o/r/issues/2"

    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_json_output(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[github]\norgs = ["o"]\n',
            encoding="utf-8",
        )
        exit_code, stdout, _ = run_cli(
            "--config", str(config), "todo", "--source", "github", "--json",
        )
        assert exit_code == 0
        data = json.loads(stdout)
        assert len(data) == 2
        assert data[0]["source"] == "github"
        assert data[0]["kind"] == "pull_request"

    def test_no_scope_errors(self, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n',
            encoding="utf-8",
        )
        exit_code, _, stderr = run_cli(
            "--config", str(config), "todo", "--source", "github",
        )
        assert exit_code != 0
        assert "--org or --repo" in stderr

    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_cli_org_overrides_config(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[github]\norgs = ["fromconfig"]\n',
            encoding="utf-8",
        )
        exit_code, _, _ = run_cli(
            "--config", str(config), "todo", "--source", "github", "--org", "fromcli",
        )
        assert exit_code == 0
        assert mock_fetch.call_args.kwargs["orgs"] == ["fromcli"]

    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_uses_config_orgs(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[github]\norgs = ["containers", "redhat"]\n'
            'repos = ["myorg/tool"]\n',
            encoding="utf-8",
        )
        exit_code, _, _ = run_cli(
            "--config", str(config), "todo", "--source", "github",
        )
        assert exit_code == 0
        kw = mock_fetch.call_args.kwargs
        assert kw["orgs"] == ["containers", "redhat"]
        assert kw["repos"] == ["myorg/tool"]

    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_multiple_orgs(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n',
            encoding="utf-8",
        )
        exit_code, _, _ = run_cli(
            "--config", str(config), "todo", "--source", "github",
            "--org", "containers", "--org", "redhat",
        )
        assert exit_code == 0
        assert mock_fetch.call_args.kwargs["orgs"] == ["containers", "redhat"]

    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_repo_filter(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n',
            encoding="utf-8",
        )
        exit_code, _, _ = run_cli(
            "--config", str(config), "todo", "--source", "github",
            "--repo", "o/r",
        )
        assert exit_code == 0
        assert mock_fetch.call_args.kwargs["repos"] == ["o/r"]


class TestTodoJira:
    @patch("notegraph.cli.jira_api.fetch_todo", return_value=_MOCK_JIRA_TODO_ITEMS)
    def test_plain_output(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[jira]\nendpoint = "test.atlassian.net"\n'
            'jql = "project = RUN"\n',
            encoding="utf-8",
        )
        exit_code, stdout, _ = run_cli(
            "--config", str(config), "todo", "--source", "jira",
        )
        assert exit_code == 0
        lines = stdout.strip().splitlines()
        assert len(lines) == 2
        assert "RUN-100" in lines[0]

    @patch("notegraph.cli.jira_api.fetch_todo", return_value=_MOCK_JIRA_TODO_ITEMS)
    def test_json_output(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[jira]\nendpoint = "test.atlassian.net"\n'
            'jql = "project = RUN"\n',
            encoding="utf-8",
        )
        exit_code, stdout, _ = run_cli(
            "--config", str(config), "todo", "--source", "jira", "--json",
        )
        assert exit_code == 0
        data = json.loads(stdout)
        assert len(data) == 2
        assert data[0]["source"] == "jira"

    @patch("notegraph.cli.jira_api.fetch_todo", return_value=_MOCK_JIRA_TODO_ITEMS)
    def test_cli_jql_overrides_config(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[jira]\nendpoint = "test.atlassian.net"\n'
            'jql = "project = FROMCONF"\n',
            encoding="utf-8",
        )
        exit_code, _, _ = run_cli(
            "--config", str(config), "todo", "--source", "jira",
            "--jql", "assignee = me",
        )
        assert exit_code == 0
        assert mock_fetch.call_args.kwargs["jql"] == "assignee = me"

    @patch("notegraph.cli.jira_api.fetch_todo", return_value=_MOCK_JIRA_TODO_ITEMS)
    def test_config_jql_used_when_no_cli_flag(self, mock_fetch, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[jira]\nendpoint = "test.atlassian.net"\n'
            'jql = "project = FROMCONF"\n',
            encoding="utf-8",
        )
        exit_code, _, _ = run_cli(
            "--config", str(config), "todo", "--source", "jira",
        )
        assert exit_code == 0
        assert mock_fetch.call_args.kwargs["jql"] == "project = FROMCONF"

    @patch("notegraph.cli.jira_api.fetch_todo", return_value=[])
    def test_empty_jql_returns_empty(self, mock_fetch, sample_config_toml):
        exit_code, stdout, _ = run_cli(
            "--config", str(sample_config_toml), "todo", "--source", "jira",
        )
        assert exit_code == 0
        assert stdout.strip() == ""


class TestTodoBothSources:
    @patch("notegraph.cli.jira_api.fetch_todo", return_value=_MOCK_JIRA_TODO_ITEMS)
    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_both_sources_by_default(self, mock_gh, mock_jira, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[github]\norgs = ["o"]\n'
            '[jira]\nendpoint = "test.atlassian.net"\n'
            'jql = "project = RUN"\n',
            encoding="utf-8",
        )
        exit_code, stdout, _ = run_cli(
            "--config", str(config), "todo",
        )
        assert exit_code == 0
        lines = stdout.strip().splitlines()
        assert len(lines) == 4
        mock_gh.assert_called_once()
        mock_jira.assert_called_once()

    @patch("notegraph.cli.jira_api.fetch_todo", return_value=[])
    @patch("notegraph.cli.github_api.fetch_todo", return_value=[])
    def test_both_empty(self, mock_gh, mock_jira, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[github]\norgs = ["o"]\n'
            '[jira]\nendpoint = "test.atlassian.net"\n'
            'jql = "project = RUN"\n',
            encoding="utf-8",
        )
        exit_code, stdout, _ = run_cli(
            "--config", str(config), "todo",
        )
        assert exit_code == 0
        assert stdout.strip() == ""


class TestTodoSync:
    @patch("notegraph.cli.writer.write")
    @patch("notegraph.cli.github_api.fetch", return_value=_MOCK_GH_CONTENT)
    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_sync_writes_worktodo_and_notes(
        self, mock_todo, mock_fetch, mock_write, tmp_path
    ):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[github]\norgs = ["o"]\n',
            encoding="utf-8",
        )
        exit_code, _, stderr = run_cli(
            "--config", str(config), "todo", "--source", "github", "--sync",
        )
        assert exit_code == 0
        assert "worktodo.md" in stderr

        worktodo = graph_dir / "worktodo.md"
        assert worktodo.is_file()
        text = worktodo.read_text(encoding="utf-8")
        assert "github.com/o/r/pull/1" in text
        assert "github.com/o/r/issues/2" in text

        assert mock_fetch.call_count == 2

    @patch("notegraph.cli.writer.write")
    @patch("notegraph.cli.github_api.fetch", side_effect=ValueError("bad url"))
    @patch("notegraph.cli.github_api.fetch_todo", return_value=_MOCK_TODO_ITEMS)
    def test_sync_skips_on_error(self, mock_todo, mock_fetch, mock_write, tmp_path):
        config = tmp_path / "cfg.toml"
        graph_dir = tmp_path / "pages"
        graph_dir.mkdir()
        config.write_text(
            f'[logseq]\ngraph_dir = "{graph_dir}"\n'
            '[github]\norgs = ["o"]\n',
            encoding="utf-8",
        )
        exit_code, _, _ = run_cli(
            "--config", str(config), "todo", "--source", "github", "--sync",
        )
        assert exit_code == 0

        worktodo = graph_dir / "worktodo.md"
        assert worktodo.is_file()


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
