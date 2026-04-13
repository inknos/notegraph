"""Tests for the Jira REST API fetcher (placeholder)."""

from __future__ import annotations

import pytest

from notegraph.jira import fetch
from notegraph.schema import JiraRef


class TestFetchJira:
    def test_raises_not_implemented(self):
        ref = JiraRef(endpoint="test.atlassian.net", key="RUN-3555")
        with pytest.raises(NotImplementedError, match="jira fetch not yet implemented"):
            fetch(ref)
