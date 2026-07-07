"""Thin orchestrator that assembles schemas and writes note files to disk.

Provides three public entry points:

- ``check()`` — compute paths and file existence (no network, no writes).
- ``render()`` — fetch-ready content to rendered strings (no writes).
- ``write()`` — render and persist files to disk.
"""

from __future__ import annotations

import logging
import re
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
    _WIKILINKS_FOR_KIND,
    expand_hash_refs,
)

logger = logging.getLogger(__name__)

_ALL_KINDS: tuple[FileKind, ...] = ("md", "note", "agent")

# Maps the wikilink suffix string used in _WIKILINKS_FOR_KIND to the FileKind
# it targets.  The empty string "" means the base (md) page.
_SUFFIX_TO_KIND: dict[str, FileKind] = {"agent": "agent", "note": "note", "": "md"}

# Matches a Logseq property line, e.g. ``- tags:: [[project]]``.
# Only lines at the very top of a file (contiguous block) are preserved.
_LOGSEQ_PROP_RE = re.compile(r"^- \w[\w-]*:: ")


def check(
    ref: GitHubRef | JiraRef,
    dest_dir: str,
    *,
    prefix: str = "",
) -> NoteTriplet:
    """Compute paths and check file existence without network calls.

    Args:
        ref: A GitHub or Jira reference.
        dest_dir: Output directory.
        prefix: Optional filename/wikilink prefix.

    Returns:
        A ``NoteTriplet`` with paths and existence flags.
    """
    paths = PathInfo.from_ref(ref, dest_dir, prefix=prefix)
    return paths.to_triplet()


def render(
    content: NoteContent,
    ref: GitHubRef | JiraRef,
    dest_dir: str,
    *,
    kinds: tuple[FileKind, ...] = _ALL_KINDS,
    prefix: str = "",
) -> dict[str, RenderedNote]:
    """Render note content into strings without writing to disk.

    Assembles headers, bodies, and footers for each requested file kind
    and returns the rendered content keyed by kind name.

    Args:
        content: Fetched note content.
        ref: A GitHub or Jira reference.
        dest_dir: Output directory (used for path computation only).
        kinds: Which file kinds to render.  Defaults to all three.
        prefix: Optional filename/wikilink prefix.

    Returns:
        Dict mapping file kind (``"md"``, ``"note"``, ``"agent"``) to a
        ``RenderedNote`` containing the target path and full file content.
    """
    paths = PathInfo.from_ref(ref, dest_dir, prefix=prefix)

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
        text = _assemble(header, body, kind, kinds=kinds)
        result[kind] = RenderedNote(path=paths.path_for(kind), content=text)

    return result


def write(
    content: NoteContent,
    ref: GitHubRef | JiraRef,
    dest_dir: str,
    *,
    kinds: tuple[FileKind, ...] = _ALL_KINDS,
    replace: bool = False,
    prefix: str = "",
) -> None:
    """Render and write note files to disk.

    By default the ``md`` (summary) file is **always overwritten**
    (regenerated from fresh data), while ``note`` and ``agent`` files
    are **never overwritten** (write-if-missing semantics).

    When *replace* is ``True``, **all** selected files are overwritten
    regardless of whether they already exist.

    Args:
        content: Fetched note content.
        ref: A GitHub or Jira reference.
        dest_dir: Output directory.
        kinds: Which file kinds to write.  Defaults to all three.
        replace: If ``True``, overwrite existing note/agent files.
        prefix: Optional filename/wikilink prefix.
    """
    rendered = render(content, ref, dest_dir, kinds=kinds, prefix=prefix)
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    for kind, note in rendered.items():
        file_path = Path(note.path)

        if not replace and kind != "md" and file_path.is_file():
            logger.info("  skip (exists): %s", file_path)
            continue

        # Preserve any Logseq property lines that external tools may have
        # prepended to the top of the md file (e.g. ``- tags:: [[project]]``).
        # We collect the contiguous block at the very top of the existing file
        # and re-prepend it so it survives a re-fetch overwrite.
        final_content = note.content
        if kind == "md" and file_path.is_file():
            existing = file_path.read_text(encoding="utf-8")
            prop_lines: list[str] = []
            for line in existing.splitlines():
                if _LOGSEQ_PROP_RE.match(line):
                    prop_lines.append(line)
                else:
                    break
            if prop_lines:
                final_content = "\n".join(prop_lines) + "\n" + final_content

        action = "updated" if file_path.is_file() else "created"
        file_path.write_text(final_content + "\n", encoding="utf-8")
        logger.info("  %s:       %s", action, file_path)


def _assemble(
    header: NoteHeader,
    body: NoteBody,
    kind: FileKind,
    *,
    kinds: tuple[FileKind, ...] = _ALL_KINDS,
) -> str:
    """Combine header, body, and footer wikilinks into a full file.

    Args:
        header: Rendered header model.
        body: Rendered body model.
        kind: Which file in the triplet.
        kinds: The full set of file kinds being generated in this render
            pass.  Used to suppress footer links to files that are not
            being created.

    Returns:
        Complete file content as a string.
    """
    header_str = header.to_string(kind)
    body_str = body.to_string(kind)
    footer = _footer(header, kind, kinds=kinds)
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


def _footer(
    header: NoteHeader,
    kind: FileKind,
    *,
    kinds: tuple[FileKind, ...] = _ALL_KINDS,
) -> str:
    """Render the wikilink footer block.

    Only emits links for sibling files that are actually being generated
    (i.e. whose kind appears in *kinds*).  Returns an empty string when
    no links survive the filter so the caller omits the footer entirely.

    Args:
        header: Header model containing wikilinks.
        kind: Which file in the triplet being assembled.
        kinds: The full set of file kinds being generated in this render
            pass.

    Returns:
        Footer string with separator and wikilinks, or ``""`` if no
        links remain after filtering.
    """
    suffixes = _WIKILINKS_FOR_KIND[kind]
    links = [
        f"[[{wl}]]"
        for suffix, wl in zip(suffixes, header.wikilinks)
        if _SUFFIX_TO_KIND[suffix] in kinds
    ]
    if not links:
        return ""
    return "\n".join(["---", "", *links])
