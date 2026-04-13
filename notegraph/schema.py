"""Pydantic models for notegraph notes, paths, and rendering.

Every "renderable" model (PathInfo, NoteHeader, NoteBody) has a
``to_string`` method that serializes the data for a given output
format (logseq, cosma).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, model_validator

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
Format = Literal["logseq", "cosma"]
FileKind = Literal["md", "note", "cursor"]

# ---------------------------------------------------------------------------
# Cosma helpers
# ---------------------------------------------------------------------------

_COSMA_KIND_TYPE: dict[FileKind, str] = {
    "md": "summary",
    "note": "notes",
    "cursor": "analysis",
}

_COSMA_LINK_TARGETS: dict[FileKind, tuple[FileKind, FileKind]] = {
    "md": ("cursor", "note"),
    "note": ("cursor", "md"),
    "cursor": ("md", "note"),
}

_COSMA_LINK_TYPE: dict[tuple[FileKind, FileKind], str] = {
    ("md", "cursor"): "with_analysis",
    ("md", "note"): "with_notes",
    ("cursor", "md"): "analyzes_summary",
    ("cursor", "note"): "with_complementary_notes",
    ("note", "md"): "annotates_summary",
    ("note", "cursor"): "with_complementary_analysis",
}


def _cosma_id(canonical: str, kind: FileKind) -> str:
    """Generate a deterministic 14-digit Cosma ID.

    The ID is derived from a SHA-256 hash of the canonical reference
    string combined with the file kind, ensuring that re-runs always
    produce the same value.

    Args:
        canonical: Canonical string identifying the resource (e.g. URL).
        kind: Which file in the triplet.

    Returns:
        A 14-digit zero-padded numeric string.
    """
    key = f"{canonical}:{kind}"
    digest = hashlib.sha256(key.encode()).hexdigest()
    return str(int(digest[:12], 16) % 10**14).zfill(14)


# ---------------------------------------------------------------------------
# Source refs — parse CLI input into structured data
# ---------------------------------------------------------------------------

_GH_URL_RE = re.compile(
    r"^https://github\.com/(?P<org>[^/]+)/(?P<repo>[^/]+)/"
    r"(?P<url_type>issues|pull)/(?P<number>\d+)",
)

_JIRA_URL_RE = re.compile(
    r"^https://(?P<host>[^/]+)/browse/(?P<key>[A-Za-z]+-\d+)",
)

_JIRA_KEY_RE = re.compile(r"^[A-Za-z]+-\d+$")


class GitHubRef(BaseModel):
    """Parsed GitHub issue or PR reference."""

    org: str
    repo: str
    url_type: Literal["issues", "pull"]
    number: int

    @classmethod
    def from_url(cls, url: str) -> GitHubRef:
        """Parse a GitHub URL into a ``GitHubRef``.

        Args:
            url: Full GitHub URL
                (``https://github.com/{org}/{repo}/{issues|pull}/{number}``).

        Returns:
            Parsed reference.

        Raises:
            ValueError: If the URL does not match the expected pattern.
        """
        match = _GH_URL_RE.match(url)
        if not match:
            msg = (
                f"URL does not match https://github.com/{{org}}/{{repo}}/"
                f"{{issues|pull}}/{{number}}: {url}"
            )
            raise ValueError(msg)
        return cls(
            org=match["org"],
            repo=match["repo"],
            url_type=match["url_type"],  # type: ignore[arg-type]
            number=int(match["number"]),
        )

    @property
    def note_type(self) -> str:
        """Return ``pull_request`` or ``issue``."""
        return "pull_request" if self.url_type == "pull" else "issue"

    @property
    def canonical_url(self) -> str:
        """Full canonical URL."""
        return f"https://github.com/{self.org}/{self.repo}/{self.url_type}/{self.number}"


class JiraRef(BaseModel):
    """Parsed Jira issue reference."""

    endpoint: str
    key: str

    @model_validator(mode="after")
    def _normalize_key(self) -> JiraRef:
        self.key = self.key.upper()
        return self

    @classmethod
    def from_string(cls, raw: str, default_endpoint: str) -> JiraRef:
        """Parse a Jira URL or bare key into a ``JiraRef``.

        Args:
            raw: Either ``https://<host>/browse/<KEY>`` or a bare key like
                ``RUN-3555``.
            default_endpoint: Fallback endpoint when *raw* is a bare key.

        Returns:
            Parsed reference.

        Raises:
            ValueError: If *raw* is neither a valid URL nor a bare key.
        """
        url_match = _JIRA_URL_RE.match(raw)
        if url_match:
            return cls(endpoint=url_match["host"], key=url_match["key"])
        if _JIRA_KEY_RE.match(raw):
            return cls(endpoint=default_endpoint, key=raw)
        msg = f"Not a valid Jira URL or issue key: {raw}"
        raise ValueError(msg)

    @property
    def browse_url(self) -> str:
        """Full browse URL."""
        return f"https://{self.endpoint}/browse/{self.key}"


# ---------------------------------------------------------------------------
# File-existence plumbing (--check output)
# ---------------------------------------------------------------------------


class FileStatus(BaseModel):
    """Path and existence flag for a single note file."""

    path: str
    exists: bool


class NoteTriplet(BaseModel):
    """The three-file note set (md, note, cursor) with existence info.

    ``model_dump()`` produces JSON compatible with the existing bash
    ``--check`` output.
    """

    md: FileStatus
    note: FileStatus
    cursor: FileStatus

    def format_table(self) -> str:
        """Render a human-readable table of the triplet.

        Returns:
            A formatted multi-line string.
        """
        rows = [
            ("md", self.md),
            ("note", self.note),
            ("cursor", self.cursor),
        ]
        path_width = max(len(r[1].path) for r in rows)
        lines = [f"  {'Kind':<8} {'Exists':<8} {'Path'}"]
        for kind, fs in rows:
            marker = "\u2713" if fs.exists else "\u2717"
            lines.append(f"  {kind:<8} {marker:<8} {fs.path:<{path_width}}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# RenderedNote — single rendered file ready for output
# ---------------------------------------------------------------------------


class RenderedNote(BaseModel):
    """A fully rendered note file with its target path.

    Used by ``writer.render()`` to return generated content without
    writing to disk — for ``--json`` preview mode.
    """

    path: str
    content: str


# ---------------------------------------------------------------------------
# PathInfo — renderable, computed from a ref + dest_dir + format
# ---------------------------------------------------------------------------


class PathInfo(BaseModel):
    """Computed file paths and wikilink prefixes for a note triplet."""

    file_prefix: str
    file_sep: str
    wikilink_prefix: str
    wikilink_sep: str
    cosma_ids: dict[str, str] = {}

    @property
    def md_path(self) -> str:
        """Path to the summary ``.md`` file."""
        return f"{self.file_prefix}.md"

    @property
    def note_path(self) -> str:
        """Path to the user notes file."""
        return f"{self.file_prefix}{self.file_sep}note.md"

    @property
    def cursor_path(self) -> str:
        """Path to the agent cursor file."""
        return f"{self.file_prefix}{self.file_sep}cursor.md"

    @property
    def wikilink(self) -> str:
        """Base wikilink (points to the summary page)."""
        return self.wikilink_prefix

    @property
    def wikilink_note(self) -> str:
        """Wikilink to the note page."""
        return f"{self.wikilink_prefix}{self.wikilink_sep}note"

    @property
    def wikilink_cursor(self) -> str:
        """Wikilink to the cursor page."""
        return f"{self.wikilink_prefix}{self.wikilink_sep}cursor"

    def path_for(self, kind: FileKind) -> str:
        """Return the file path for the given *kind*."""
        return {"md": self.md_path, "note": self.note_path, "cursor": self.cursor_path}[kind]

    def to_triplet(self) -> NoteTriplet:
        """Check file existence and return a ``NoteTriplet``."""
        return NoteTriplet(
            md=FileStatus(path=self.md_path, exists=Path(self.md_path).is_file()),
            note=FileStatus(path=self.note_path, exists=Path(self.note_path).is_file()),
            cursor=FileStatus(path=self.cursor_path, exists=Path(self.cursor_path).is_file()),
        )

    # -- factory classmethods -----------------------------------------------

    @classmethod
    def from_github(cls, ref: GitHubRef, dest_dir: str, fmt: Format) -> PathInfo:
        """Build ``PathInfo`` for a GitHub ref.

        Args:
            ref: Parsed GitHub reference.
            dest_dir: Output directory.
            fmt: Output format (``logseq`` or ``cosma``).

        Returns:
            Computed path info.
        """
        if fmt == "cosma":
            slug = f"github-{ref.org}-{ref.repo}-{ref.url_type}-{ref.number}"
            file_prefix = f"{dest_dir}/{slug}"
            canonical = ref.canonical_url
            ids = {k: _cosma_id(canonical, k) for k in ("md", "note", "cursor")}
            return cls(
                file_prefix=file_prefix,
                file_sep="-",
                wikilink_prefix="",
                wikilink_sep="",
                cosma_ids=ids,
            )

        page_ns = f"github.com___{ref.org}___{ref.repo}___{ref.url_type}"
        file_prefix = f"{dest_dir}/{page_ns}___{ref.number}"
        wikilink_prefix = f"github.com/{ref.org}/{ref.repo}/{ref.url_type}/{ref.number}"
        return cls(
            file_prefix=file_prefix,
            file_sep="___",
            wikilink_prefix=wikilink_prefix,
            wikilink_sep="/",
        )

    @classmethod
    def from_jira(cls, ref: JiraRef, dest_dir: str, fmt: Format) -> PathInfo:
        """Build ``PathInfo`` for a Jira ref.

        Args:
            ref: Parsed Jira reference.
            dest_dir: Output directory.
            fmt: Output format (``logseq`` or ``cosma``).

        Returns:
            Computed path info.
        """
        if fmt == "cosma":
            slug = f"jira-{ref.key}"
            file_prefix = f"{dest_dir}/{slug}"
            canonical = ref.browse_url
            ids = {k: _cosma_id(canonical, k) for k in ("md", "note", "cursor")}
            return cls(
                file_prefix=file_prefix,
                file_sep="-",
                wikilink_prefix="",
                wikilink_sep="",
                cosma_ids=ids,
            )

        file_prefix = f"{dest_dir}/{ref.endpoint}___{ref.key}"
        wikilink_prefix = f"{ref.endpoint}/{ref.key}"
        return cls(
            file_prefix=file_prefix,
            file_sep="___",
            wikilink_prefix=wikilink_prefix,
            wikilink_sep="/",
        )

    @classmethod
    def from_ref(
        cls,
        ref: GitHubRef | JiraRef,
        dest_dir: str,
        fmt: Format,
    ) -> PathInfo:
        """Dispatch to ``from_github`` or ``from_jira``.

        Args:
            ref: A GitHub or Jira reference.
            dest_dir: Output directory.
            fmt: Output format.

        Returns:
            Computed path info.
        """
        if isinstance(ref, GitHubRef):
            return cls.from_github(ref, dest_dir, fmt)
        return cls.from_jira(ref, dest_dir, fmt)


# ---------------------------------------------------------------------------
# Note content — format-agnostic fetched data
# ---------------------------------------------------------------------------


class Comment(BaseModel):
    """A single comment on an issue or PR."""

    author: str
    date: str
    body: str


class NoteContent(BaseModel):
    """Fetched data for an issue or PR, independent of output format."""

    title: str
    url: str
    source: Literal["github", "jira"]
    status: str
    author: str
    created: str
    description: str
    comments: list[Comment] = []
    note_type: str = "issue"
    extra: dict[str, Any] = {}


class TodoItem(BaseModel):
    """A single actionable item from a todo search.

    Works for both GitHub and Jira.  The *source* field distinguishes
    origin, *kind* carries the raw item type, and *state* carries the
    raw platform state without normalization.
    """

    url: str
    title: str
    source: Literal["github", "jira"]
    kind: str
    state: str
    repo: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# NoteTags — structured tag data with format-specific rendering
# ---------------------------------------------------------------------------


class NoteTags(BaseModel):
    """Structured tag data, format-agnostic.

    Holds the raw tag facets and renders them for each output format.
    """

    source: Literal["github", "jira"]
    kind: str
    org_repo: str = ""

    def to_cosma_tags(self) -> list[str]:
        """Render as a flat list for the Cosma YAML ``tags`` field.

        Returns:
            Ordered list of tag strings.
        """
        tags = [self.source, self.kind]
        if self.org_repo:
            tags.append(self.org_repo)
        return tags

    def to_logseq_tags(self) -> dict[str, str]:
        """Render as Logseq page properties. Placeholder — TBD.

        Returns:
            Empty dict (not yet implemented).
        """
        return {}

    @classmethod
    def from_github_ref(cls, ref: GitHubRef) -> NoteTags:
        """Build tags from a GitHub reference.

        Args:
            ref: Parsed GitHub reference.

        Returns:
            Populated tags.
        """
        return cls(
            source="github",
            kind=ref.note_type,
            org_repo=f"{ref.org}/{ref.repo}",
        )

    @classmethod
    def from_jira_content(cls, content: NoteContent) -> NoteTags:
        """Build tags from Jira note content.

        Args:
            content: Fetched note content (provides ``note_type``).

        Returns:
            Populated tags.
        """
        return cls(source="jira", kind=content.note_type)


# ---------------------------------------------------------------------------
# NoteHeader — renderable top section of each file
# ---------------------------------------------------------------------------

_WIKILINKS_FOR_KIND: dict[FileKind, tuple[str, str]] = {
    "md": ("cursor", "note"),
    "note": ("cursor", ""),
    "cursor": ("", "note"),
}


class NoteHeader(BaseModel):
    """Structured header data for a note file."""

    title: str
    url: str
    note_type: str
    status: str
    author: str
    created: str
    wikilinks: list[str]
    cosma_id: str = ""
    tags: NoteTags | None = None

    def to_string(self, fmt: Format, kind: FileKind) -> str:
        """Render the header as a string for the given format and file kind.

        Args:
            fmt: Output format.
            kind: Which file in the triplet (md, note, cursor).

        Returns:
            Rendered header string.
        """
        if fmt == "cosma":
            return self._to_cosma(kind)
        return self._to_logseq(kind)

    def _to_cosma(self, kind: FileKind) -> str:
        title = self.title.replace('"', '\\"')
        lines = [
            "---",
            f'title: "{title}"',
            f"id: {self.cosma_id}",
            f"type: {_COSMA_KIND_TYPE[kind]}",
            f"author: {self.author}",
        ]
        if self.tags:
            lines.append("tags:")
            lines.extend(f"- {tag}" for tag in self.tags.to_cosma_tags())
        lines.extend(["---", "", self.url, ""])
        return "\n".join(lines)

    def _to_logseq(self, kind: FileKind) -> str:
        lines = [f"# {self.title}", "", self.url, ""]
        if kind in ("md", "cursor"):
            meta_parts = []
            if kind == "cursor":
                meta_parts.append(f"**Type:** {self.note_type}")
            meta_parts.extend(
                [
                    f"**Status:** {self.status}",
                    f"**Author:** {self.author}" if kind == "cursor" else "",
                    f"**Created:** {self.created}" if kind == "cursor" else "",
                ]
            )
            meta_parts = [p for p in meta_parts if p]
            if kind == "cursor":
                lines.append(" | ".join(meta_parts))
                lines.append("")
        return "\n".join(lines)

    @classmethod
    def from_content(
        cls,
        content: NoteContent,
        paths: PathInfo,
        kind: FileKind,
        *,
        fmt: Format = "logseq",
        tags: NoteTags | None = None,
    ) -> NoteHeader:
        """Build a ``NoteHeader`` from content and path info.

        Args:
            content: Fetched note content.
            paths: Computed path info.
            kind: Which file in the triplet.
            fmt: Output format (determines wikilink style).
            tags: Structured tags (required for cosma).

        Returns:
            Populated header.
        """
        if fmt == "cosma":
            link_targets = _COSMA_LINK_TARGETS[kind]
            wikilinks = []
            for target_kind in link_targets:
                target_id = paths.cosma_ids[target_kind]
                display = _COSMA_KIND_TYPE[target_kind]
                link_type = _COSMA_LINK_TYPE[(kind, target_kind)]
                wikilinks.append(f"{link_type}:{target_id}|{display}")
            return cls(
                title=content.title,
                url=content.url,
                note_type=content.note_type,
                status=content.status,
                author=content.author,
                created=content.created,
                wikilinks=wikilinks,
                cosma_id=paths.cosma_ids[kind],
                tags=tags,
            )

        suffixes = _WIKILINKS_FOR_KIND[kind]
        wikilinks = []
        for suffix in suffixes:
            if not suffix:
                wikilinks.append(paths.wikilink)
            else:
                wikilinks.append(f"{paths.wikilink_prefix}{paths.wikilink_sep}{suffix}")
        return cls(
            title=content.title,
            url=content.url,
            note_type=content.note_type,
            status=content.status,
            author=content.author,
            created=content.created,
            wikilinks=wikilinks,
        )


# ---------------------------------------------------------------------------
# NoteBody — renderable main content of each file
# ---------------------------------------------------------------------------


class Section(BaseModel):
    """A named section in a note body."""

    heading: str
    content: str = ""


class NoteBody(BaseModel):
    """Structured body data for a note file."""

    description: str = ""
    comments: list[Comment] = []
    sections: list[Section] = []

    def to_string(self, fmt: Format, kind: FileKind) -> str:
        """Render the body as a string for the given format and file kind.

        Args:
            fmt: Output format.
            kind: Which file in the triplet (md, note, cursor).

        Returns:
            Rendered body string.
        """
        if fmt == "cosma":
            return self._to_cosma(kind)
        return self._to_logseq(kind)

    @staticmethod
    def _strip_md_images(text: str) -> str:
        """Convert ``![alt](url)`` to ``[alt](url)`` so Cosma won't resolve images."""
        return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"[\1](\2)", text)

    def _to_cosma(self, kind: FileKind) -> str:
        """Cosma body — same as Logseq but with image syntax stripped."""
        return self._strip_md_images(self._to_logseq(kind))

    def _to_logseq(self, kind: FileKind) -> str:
        if kind == "md":
            return self._to_logseq_md()
        if kind == "note":
            return self._to_logseq_note()
        return self._to_logseq_cursor()

    def _to_logseq_md(self) -> str:
        parts = ["## Description", "", self.description, "", "## Comments", ""]
        for comment in self.comments:
            parts.append(f"### @{comment.author} ({comment.date})")
            parts.extend(["", comment.body, ""])
        for section in self.sections:
            parts.append(f"## {section.heading}")
            parts.extend(["", section.content, ""])
        return "\n".join(parts)

    def _to_logseq_note(self) -> str:
        parts: list[str] = []
        for section in self.sections:
            parts.append(f"## {section.heading}")
            parts.extend(["", section.content, ""] if section.content else [""])
        return "\n".join(parts)

    def _to_logseq_cursor(self) -> str:
        parts: list[str] = []
        for section in self.sections:
            parts.append(f"## {section.heading}")
            parts.extend(["", section.content, ""] if section.content else [""])
        return "\n".join(parts)

    @classmethod
    def from_content(cls, content: NoteContent, kind: FileKind) -> NoteBody:
        """Build a ``NoteBody`` from content for a given file kind.

        Args:
            content: Fetched note content.
            kind: Which file in the triplet.

        Returns:
            Populated body.
        """
        if kind == "md":
            sections = [
                Section(
                    heading="Key Discussion Points",
                    content="<!-- summarize the above comments here -->",
                )
            ]
            return cls(
                description=content.description,
                comments=content.comments,
                sections=sections,
            )
        if kind == "note":
            return cls(
                sections=[
                    Section(heading="Notes"),
                    Section(heading="TODOs"),
                    Section(heading="Related"),
                ]
            )
        return cls(
            sections=[
                Section(heading="Analysis"),
                Section(heading="TODOs"),
            ]
        )
