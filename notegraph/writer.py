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
    Comment,
    FileKind,
    GitHubRef,
    JiraRef,
    NoteBody,
    NoteContent,
    NoteHeader,
    NoteTriplet,
    PathInfo,
    RenderedNote,
    expand_hash_refs,
)

logger = logging.getLogger(__name__)

_ALL_KINDS: tuple[FileKind, ...] = ("md", "note", "cursor")


def check(
    ref: GitHubRef | JiraRef,
    dest_dir: str,
) -> NoteTriplet:
    """Compute paths and check file existence without network calls.

    Args:
        ref: A GitHub or Jira reference.
        dest_dir: Output directory.

    Returns:
        A ``NoteTriplet`` with paths and existence flags.
    """
    paths = PathInfo.from_ref(ref, dest_dir)
    return paths.to_triplet()


def render(
    content: NoteContent,
    ref: GitHubRef | JiraRef,
    dest_dir: str,
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
        kinds: Which file kinds to render.  Defaults to all three.

    Returns:
        Dict mapping file kind (``"md"``, ``"note"``, ``"cursor"``) to a
        ``RenderedNote`` containing the target path and full file content.
    """
    paths = PathInfo.from_ref(ref, dest_dir)

    if isinstance(ref, GitHubRef):
        expanded = _expand_content(content, ref.org, ref.repo)
    else:
        expanded = content

    result: dict[str, RenderedNote] = {}
    for kind in kinds:
        effective = (
            expanded
            if kind == "md"
            else content.model_copy(
                update={"title": expanded.title},
            )
        )
        header = NoteHeader.from_content(effective, paths, kind)
        body = NoteBody.from_content(effective, kind)
        text = _assemble(header, body, kind)
        result[kind] = RenderedNote(path=paths.path_for(kind), content=text)

    return result


def write(
    content: NoteContent,
    ref: GitHubRef | JiraRef,
    dest_dir: str,
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
        kinds: Which file kinds to write.  Defaults to all three.
        replace: If ``True``, overwrite existing note/cursor files.
    """
    rendered = render(content, ref, dest_dir, kinds=kinds)
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
    kind: FileKind,
) -> str:
    """Combine header, body, and footer wikilinks into a full file.

    Args:
        header: Rendered header model.
        body: Rendered body model.
        kind: Which file in the triplet.

    Returns:
        Complete file content as a string.
    """
    header_str = header.to_string(kind)
    body_str = body.to_string(kind)
    footer = _footer(header, kind)
    return f"{header_str}{body_str}{footer}"


def _expand_content(content: NoteContent, org: str, repo: str) -> NoteContent:
    """Return a copy of *content* with ``#N`` refs expanded to wikilinks.

    Args:
        content: Original note content.
        org: GitHub organisation / owner.
        repo: GitHub repository name.

    Returns:
        A shallow copy with title, description, and comment bodies expanded.
    """
    return content.model_copy(
        update={
            "title": expand_hash_refs(content.title, org, repo),
            "description": expand_hash_refs(content.description, org, repo),
            "comments": [
                Comment(
                    author=c.author,
                    date=c.date,
                    body=expand_hash_refs(c.body, org, repo),
                )
                for c in content.comments
            ],
        },
    )


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
