"""Worktodo page generation — parse, merge, and write ``worktodo.md``."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from pathlib import Path

    from notegraph.schema import TodoItem

_WIKILINK_RE = re.compile(r"^- \[\[([^\]]+)\]\]")
_GH_URL_RE = re.compile(
    r"https?://github\.com/(?P<org>[^/]+)/(?P<repo>[^/]+)"
    r"/(?P<type>issues|pull)/(?P<num>\d+)",
)
_JIRA_URL_RE = re.compile(
    r"https?://(?P<host>[^/]+)/browse/(?P<key>[A-Z]+-\d+)",
)


class WorktodoPage(BaseModel):
    """In-memory representation of a ``worktodo.md`` file."""

    focus: list[str] = []
    backlog: list[str] = []
    incoming: list[str] = []
    items: dict[str, str] = {}


def item_to_wikilink(item: TodoItem) -> str:
    """Derive a Logseq wikilink from a ``TodoItem`` URL.

    Args:
        item: The todo item.

    Returns:
        Wikilink string (without brackets), e.g.
        ``github.com/org/repo/pull/1`` or ``host.net/KEY-123``.
    """
    gh = _GH_URL_RE.match(item.url)
    if gh:
        return f"github.com/{gh['org']}/{gh['repo']}/{gh['type']}/{gh['num']}"

    jira = _JIRA_URL_RE.match(item.url)
    if jira:
        return f"{jira['host']}/{jira['key']}"

    return item.url


def item_to_line(item: TodoItem) -> str:
    """Format a ``TodoItem`` as a worktodo markdown line.

    Args:
        item: The todo item.

    Returns:
        A markdown list item, e.g.
        ``- [[github.com/o/r/pull/1]] title (**open**)``.
    """
    wl = item_to_wikilink(item)

    if item.source == "jira":
        jira = _JIRA_URL_RE.match(item.url)
        key = jira["key"] if jira else ""
        return f"- [[{wl}]] {key} {item.title} (**{item.state}**)"

    return f"- [[{wl}]] {item.title} (**{item.state}**)"


_SECTION_HEADERS: dict[str, str] = {
    "## Focus": "focus",
    "## Backlog": "backlog",
    "## Incoming": "incoming",
}


def parse_worktodo(path: Path) -> WorktodoPage:
    """Parse an existing ``worktodo.md`` into a ``WorktodoPage``.

    Extracts wikilinks per section (Focus, Backlog, Incoming) and
    preserves the full formatted lines.  Returns an empty page if the
    file does not exist.

    Args:
        path: Path to the ``worktodo.md`` file.

    Returns:
        Parsed page with section lists and item map.
    """
    if not path.is_file():
        return WorktodoPage()

    sections: dict[str, list[str]] = {"focus": [], "backlog": [], "incoming": []}
    items: dict[str, str] = {}
    current = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        current = _SECTION_HEADERS.get(line, "" if line.startswith("## ") else current)

        m = _WIKILINK_RE.match(line)
        if m and current in sections:
            wl = m.group(1)
            items[wl] = line
            sections[current].append(wl)

    return WorktodoPage(
        focus=sections["focus"],
        backlog=sections["backlog"],
        incoming=sections["incoming"],
        items=items,
    )


def merge_worktodo(
    existing: WorktodoPage,
    fresh: list[TodoItem],
) -> WorktodoPage:
    """Merge fresh todo items into an existing worktodo page.

    Focus and Backlog ordering from *existing* is preserved; stale items
    (not in *fresh*) are dropped.  All items not already placed in Focus
    or Backlog land in Incoming.

    Args:
        existing: Previously parsed worktodo page.
        fresh: Newly fetched todo items.

    Returns:
        A new ``WorktodoPage`` ready for writing.
    """
    fresh_items: dict[str, str] = {}
    for item in fresh:
        wl = item_to_wikilink(item)
        fresh_items[wl] = item_to_line(item)

    focus = [wl for wl in existing.focus if wl in fresh_items]
    backlog = [wl for wl in existing.backlog if wl in fresh_items]

    placed = set(focus) | set(backlog)
    incoming = [wl for wl in fresh_items if wl not in placed]

    return WorktodoPage(
        focus=focus,
        backlog=backlog,
        incoming=incoming,
        items=fresh_items,
    )


def write_worktodo(page: WorktodoPage, path: Path) -> None:
    """Write a ``WorktodoPage`` to disk as ``worktodo.md``.

    Args:
        page: The page to write.
        path: Destination file path.
    """
    today = datetime.now(tz=UTC).date().isoformat()
    lines = [
        "# Worktodo",
        "",
        f"*Updated: {today}*",
        "",
        "## Focus",
        "",
    ]
    lines.extend(page.items[wl] for wl in page.focus if wl in page.items)
    lines += ["", "## Backlog", ""]
    lines.extend(page.items[wl] for wl in page.backlog if wl in page.items)
    lines += ["", "## Incoming", ""]
    lines.extend(page.items[wl] for wl in page.incoming if wl in page.items)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
