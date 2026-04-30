"""Tests for config loading: TOML parsing, env vars, precedence."""

from __future__ import annotations

import pytest

from notegraph.cli import load_config


class TestValidToml:
    def test_all_sections_parsed(self, sample_config_toml):
        cfg = load_config(sample_config_toml)
        assert cfg.jira.endpoint == "test.atlassian.net"
        assert cfg.jira.email == "dev@example.com"
        assert cfg.jira.token == "jira-secret"
        assert cfg.jira.repo == "~/projects/jira"
        assert cfg.github.token == "gh-secret"
        assert cfg.vikunja.base_url == "http://vikunja.test:3456"
        assert cfg.vikunja.token == "vk-secret"

    def test_logseq_graph_dir(self, sample_config_toml):
        cfg = load_config(sample_config_toml)
        assert "logseq_pages" in cfg.logseq.graph_dir


class TestPartialToml:
    def test_missing_jira_section(self, tmp_path):
        cfg_path = tmp_path / "partial.toml"
        cfg_path.write_text("", encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.jira.endpoint == ""
        assert cfg.jira.token == ""

    def test_missing_github_section(self, tmp_path):
        cfg_path = tmp_path / "partial.toml"
        cfg_path.write_text("", encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.github.token == ""

    def test_missing_vikunja_section(self, tmp_path):
        cfg_path = tmp_path / "partial.toml"
        cfg_path.write_text("", encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.vikunja.token == ""
        assert "127.0.0.1:3456" in cfg.vikunja.base_url


class TestEmptyConfig:
    def test_empty_file(self, tmp_path):
        cfg_path = tmp_path / "empty.toml"
        cfg_path.write_text("", encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.jira.endpoint == ""

    def test_missing_file_uses_defaults(self, tmp_path):
        cfg_path = tmp_path / "nonexistent.toml"
        cfg = load_config(cfg_path)
        assert cfg.jira.endpoint == ""
        assert cfg.github.token == ""


class TestJqlConfig:
    def test_default_jql_is_empty(self, tmp_path):
        cfg_path = tmp_path / "empty.toml"
        cfg_path.write_text("", encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.jira.jql == ""

    def test_jql_from_toml(self, tmp_path):
        cfg_path = tmp_path / "jql.toml"
        cfg_path.write_text(
            '[jira]\njql = "assignee = currentUser()"',
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        assert cfg.jira.jql == "assignee = currentUser()"


class TestDestDir:
    def test_logseq_dest_dir(self, sample_config_toml):
        cfg = load_config(sample_config_toml)
        assert "logseq_pages" in cfg.dest_dir


class TestEnvVarOverrides:
    def test_jira_token_from_env(self, sample_config_toml, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "env-jira-token")
        cfg = load_config(sample_config_toml)
        assert cfg.jira.token == "env-jira-token"

    def test_github_token_from_env(self, sample_config_toml, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "env-gh-token")
        cfg = load_config(sample_config_toml)
        assert cfg.github.token == "env-gh-token"

    def test_vikunja_token_from_env(self, sample_config_toml, monkeypatch):
        monkeypatch.setenv("VIKUNJA_TOKEN", "env-vk-token")
        cfg = load_config(sample_config_toml)
        assert cfg.vikunja.token == "env-vk-token"

    def test_vikunja_base_url_from_env(self, sample_config_toml, monkeypatch):
        monkeypatch.setenv("VIKUNJA_BASE_URL", "http://custom:9999")
        cfg = load_config(sample_config_toml)
        assert cfg.vikunja.base_url == "http://custom:9999"

    def test_jira_email_from_env(self, sample_config_toml, monkeypatch):
        monkeypatch.setenv("JIRA_EMAIL", "env@example.com")
        cfg = load_config(sample_config_toml)
        assert cfg.jira.email == "env@example.com"

    def test_jira_endpoint_from_env(self, sample_config_toml, monkeypatch):
        monkeypatch.setenv("JIRA_ENDPOINT", "other.atlassian.net")
        cfg = load_config(sample_config_toml)
        assert cfg.jira.endpoint == "other.atlassian.net"

    def test_env_overrides_toml(self, sample_config_toml, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "from-env")
        cfg = load_config(sample_config_toml)
        assert cfg.jira.token == "from-env"

    def test_env_overrides_with_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fallback-token")
        cfg = load_config(tmp_path / "missing.toml")
        assert cfg.github.token == "fallback-token"


class TestInvalidToml:
    def test_malformed_toml(self, tmp_path):
        cfg_path = tmp_path / "bad.toml"
        cfg_path.write_text("this is not [valid toml", encoding="utf-8")
        with pytest.raises(Exception):  # noqa: B017
            load_config(cfg_path)
