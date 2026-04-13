"""Thin orchestrator that assembles schemas and writes note files to disk.

Provides three public entry points:

- ``check()`` — compute paths and file existence (no network, no writes).
- ``render()`` — fetch-ready content to rendered strings (no writes).
- ``write()`` — render and persist files to disk.
"""

from __future__ import annotations

import logging
from pathlib import Path

from notegraph.schema import (
    FileKind,
    Format,
    GitHubRef,
    JiraRef,
    NoteBody,
    NoteContent,
    NoteHeader,
    NoteTags,
    NoteTriplet,
    PathInfo,
    RenderedNote,
)

logger = logging.getLogger(__name__)

_ALL_KINDS: tuple[FileKind, ...] = ("md", "note", "cursor")


def check(
    ref: GitHubRef | JiraRef,
    dest_dir: str,
    fmt: Format,
) -> NoteTriplet:
    """Compute paths and check file existence without network calls.

    Args:
        ref: A GitHub or Jira reference.
        dest_dir: Output directory.
        fmt: Output format.

    Returns:
        A ``NoteTriplet`` with paths and existence flags.
    """
    paths = PathInfo.from_ref(ref, dest_dir, fmt)
    return paths.to_triplet()


def render(
    content: NoteContent,
    ref: GitHubRef | JiraRef,
    dest_dir: str,
    fmt: Format,
    *,
    kinds: tuple[FileKind, ...] = _ALL_KINDS,
) -> dict[str, RenderedNote]:
    """Render note content into strings without writing to disk.

    Assembles headers, bodies, and footers for each requested file kind
    and returns the rendered content keyed by kind name.

    Args:
        content: Fetched note content.
        ref: A GitHub or Jira reference.
        dest_dir: Output directory (used for path computation only).
        fmt: Output format.
        kinds: Which file kinds to render.  Defaults to all three.

    Returns:
        Dict mapping file kind (``"md"``, ``"note"``, ``"cursor"``) to a
        ``RenderedNote`` containing the target path and full file content.
    """
    paths = PathInfo.from_ref(ref, dest_dir, fmt)

    tags: NoteTags | None = None
    if fmt == "cosma":
        if isinstance(ref, GitHubRef):
            tags = NoteTags.from_github_ref(ref)
        else:
            tags = NoteTags.from_jira_content(content)

    result: dict[str, RenderedNote] = {}
    for kind in kinds:
        header = NoteHeader.from_content(content, paths, kind, fmt=fmt, tags=tags)
        body = NoteBody.from_content(content, kind)
        text = _assemble(header, body, fmt, kind)
        result[kind] = RenderedNote(path=paths.path_for(kind), content=text)

    return result


def write(  # noqa: PLR0913
    content: NoteContent,
    ref: GitHubRef | JiraRef,
    dest_dir: str,
    fmt: Format,
    *,
    kinds: tuple[FileKind, ...] = _ALL_KINDS,
    replace: bool = False,
) -> None:
    """Render and write note files to disk.

    By default the ``md`` (summary) file is **always overwritten**
    (regenerated from fresh data), while ``note`` and ``cursor`` files
    are **never overwritten** (write-if-missing semantics).

    When *replace* is ``True``, **all** selected files are overwritten
    regardless of whether they already exist.

    Args:
        content: Fetched note content.
        ref: A GitHub or Jira reference.
        dest_dir: Output directory.
        fmt: Output format.
        kinds: Which file kinds to write.  Defaults to all three.
        replace: If ``True``, overwrite existing note/cursor files.
    """
    rendered = render(content, ref, dest_dir, fmt, kinds=kinds)
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    for kind, note in rendered.items():
        file_path = Path(note.path)

        if not replace and kind != "md" and file_path.is_file():
            logger.info("  skip (exists): %s", file_path)
            continue

        file_path.write_text(note.content + "\n", encoding="utf-8")
        action = "updated" if file_path.is_file() else "created"
        logger.info("  %s:       %s", action, file_path)


def _assemble(
    header: NoteHeader,
    body: NoteBody,
    fmt: Format,
    kind: FileKind,
) -> str:
    """Combine header, body, and footer wikilinks into a full file.

    Args:
        header: Rendered header model.
        body: Rendered body model.
        fmt: Output format.
        kind: Which file in the triplet.

    Returns:
        Complete file content as a string.
    """
    header_str = header.to_string(fmt, kind)
    body_str = body.to_string(fmt, kind)
    footer = _footer(header, kind)
    return f"{header_str}{body_str}{footer}"


def _footer(header: NoteHeader, kind: FileKind) -> str:  # noqa: ARG001
    """Render the wikilink footer block.

    Args:
        header: Header model containing wikilinks.
        kind: Which file in the triplet (unused, kept for future use).

    Returns:
        Footer string with separator and wikilinks.
    """
    lines = ["---", ""]
    lines.extend(f"[[{wl}]]" for wl in header.wikilinks)
    return "\n".join(lines)
