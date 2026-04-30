"""Tests for Vikunja waiting sync helpers."""

from __future__ import annotations

from notegraph.vikunja_sync import (
    _canonical_sync_id,
    _extract_sync_id,
    _github_sync_slug,
    _jira_sync_slug,
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
