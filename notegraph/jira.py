"""Jira REST API client — placeholder for future implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from notegraph.schema import JiraRef, NoteContent


def fetch(
    ref: JiraRef,
    *,
    email: str = "",
    token: str = "",
) -> NoteContent:
    """Fetch issue data from the Jira REST API.

    Args:
        ref: Parsed Jira reference.
        email: Jira account email for basic auth.
        token: Jira API token.

    Raises:
        NotImplementedError: Always — not yet implemented.
    """
    msg = "jira fetch not yet implemented"
    raise NotImplementedError(msg)
