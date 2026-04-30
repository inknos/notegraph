"""Shared fixtures for notegraph tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from notegraph.schema import (
    Comment,
    GitHubRef,
    JiraRef,
    NoteContent,
)

SAMPLE_TOML = """\
[jira]
endpoint = "test.atlassian.net"
email = "dev@example.com"
token = "jira-secret"
repo = "~/projects/jira"

[github]
token = "gh-secret"

[vikunja]
base_url = "http://vikunja.test:3456"
token = "vk-secret"
github_search_query = ""

[logseq]
graph_dir = "{graph_dir}"
"""


@pytest.fixture
def tmp_dest_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "pages"
    dest.mkdir()
    return dest


@pytest.fixture
def sample_github_ref() -> GitHubRef:
    return GitHubRef(org="containers", repo="podman", url_type="pull", number=24126)


@pytest.fixture
def sample_jira_ref() -> JiraRef:
    return JiraRef(endpoint="test.atlassian.net", key="RUN-3555")


@pytest.fixture
def sample_note_content() -> NoteContent:
    return NoteContent(
        title="Fix container networking regression",
        url="https://github.com/containers/podman/pull/24126",
        source="github",
        status="open",
        author="developer",
        created="2024-03-15",
        description="This PR fixes the networking regression introduced in v5.0.",
        comments=[
            Comment(author="reviewer1", date="2024-03-16", body="LGTM, minor nit on line 42."),
            Comment(author="reviewer2", date="2024-03-17", body="Needs rebase."),
        ],
        note_type="pull_request",
        extra={"mergedAt": None},
    )


@pytest.fixture
def sample_jira_content() -> NoteContent:
    return NoteContent(
        title="Implement retry logic for API calls",
        url="https://test.atlassian.net/browse/RUN-3555",
        source="jira",
        status="In Progress",
        author="Unassigned",
        created="2024-01-10",
        description="Add exponential backoff retry logic to external API calls.",
        comments=[
            Comment(
                author="PM User",
                date="2024-01-12",
                body="Priority raised to high.",
            ),
        ],
        note_type="issue",
        extra={"assignee": "Unassigned"},
    )


@pytest.fixture
def sample_config_toml(tmp_path: Path) -> Path:
    config_path = tmp_path / "notegraph.toml"
    graph_dir = tmp_path / "logseq_pages"
    graph_dir.mkdir()
    config_path.write_text(
        SAMPLE_TOML.format(graph_dir=graph_dir),
        encoding="utf-8",
    )
    return config_path
