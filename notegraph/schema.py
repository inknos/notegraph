"""Pydantic models for notegraph notes, paths, and rendering."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, model_validator

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
Format = Literal["logseq"]
FileKind = Literal["md", "note", "agent"]

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

_HASH_REF_RE = re.compile(r"(^|[^\[&])#(\d+)")


def expand_hash_refs(text: str, org: str, repo: str) -> str:
    """Replace bare ``#N`` references with Logseq wikilinks.

    ``#123`` becomes ``[[github.com/{org}/{repo}/issues/123]]``.
    Already-linked refs (preceded by ``[``) and HTML entities
    (preceded by ``&``) are left alone.  Always uses the ``/issues/``
    path — GitHub treats it as an alias for PRs.

    Args:
        text: Raw text potentially containing ``#N`` references.
        org: GitHub organisation / owner.
        repo: GitHub repository name.

    Returns:
        Text with bare hash refs expanded to wikilinks.
    """
    return _HASH_REF_RE.sub(rf"\1[[github.com/{org}/{repo}/issues/\2]]", text)


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
    """The three-file note set (md, note, agent) with existence info.

    ``model_dump()`` produces JSON compatible with the existing bash
    ``--check`` output.
    """

    md: FileStatus
    note: FileStatus
    agent: FileStatus

    def format_table(self) -> str:
        """Render a human-readable table of the triplet.

        Returns:
            A formatted multi-line string.
        """
        rows = [
            ("md", self.md),
            ("note", self.note),
            ("agent", self.agent),
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
# PathInfo — renderable, computed from a ref + dest_dir
# ---------------------------------------------------------------------------


class PathInfo(BaseModel):
    """Computed file paths and wikilink prefixes for a note triplet."""

    file_prefix: str
    file_sep: str
    wikilink_prefix: str
    wikilink_sep: str

    @property
    def md_path(self) -> str:
        """Path to the summary ``.md`` file."""
        return f"{self.file_prefix}.md"

    @property
    def note_path(self) -> str:
        """Path to the user notes file."""
        return f"{self.file_prefix}{self.file_sep}note.md"

    @property
    def agent_path(self) -> str:
        """Path to the agent analysis file."""
        return f"{self.file_prefix}{self.file_sep}agent.md"

    @property
    def wikilink(self) -> str:
        """Base wikilink (points to the summary page)."""
        return self.wikilink_prefix

    @property
    def wikilink_note(self) -> str:
        """Wikilink to the note page."""
        return f"{self.wikilink_prefix}{self.wikilink_sep}note"

    @property
    def wikilink_agent(self) -> str:
        """Wikilink to the agent page."""
        return f"{self.wikilink_prefix}{self.wikilink_sep}agent"

    def path_for(self, kind: FileKind) -> str:
        """Return the file path for the given *kind*."""
        return {"md": self.md_path, "note": self.note_path, "agent": self.agent_path}[kind]

    def to_triplet(self) -> NoteTriplet:
        """Check file existence and return a ``NoteTriplet``."""
        return NoteTriplet(
            md=FileStatus(path=self.md_path, exists=Path(self.md_path).is_file()),
            note=FileStatus(path=self.note_path, exists=Path(self.note_path).is_file()),
            agent=FileStatus(path=self.agent_path, exists=Path(self.agent_path).is_file()),
        )

    # -- factory classmethods -----------------------------------------------

    @classmethod
    def from_github(cls, ref: GitHubRef, dest_dir: str, prefix: str = "") -> PathInfo:
        """Build ``PathInfo`` for a GitHub ref.

        Args:
            ref: Parsed GitHub reference.
            dest_dir: Output directory.
            prefix: Optional filename/wikilink prefix (e.g. ``"Wiki___Items___"``).
                Uses ``___`` as the separator in filenames and ``/`` in wikilinks.

        Returns:
            Computed path info.
        """
        page_ns = f"github.com___{ref.org}___{ref.repo}___{ref.url_type}"
        file_prefix = f"{dest_dir}/{prefix}{page_ns}___{ref.number}"
        wikilink_ns = prefix.replace("___", "/") if prefix else ""
        wikilink_prefix = f"{wikilink_ns}github.com/{ref.org}/{ref.repo}/{ref.url_type}/{ref.number}"
        return cls(
            file_prefix=file_prefix,
            file_sep="___",
            wikilink_prefix=wikilink_prefix,
            wikilink_sep="/",
        )

    @classmethod
    def from_jira(cls, ref: JiraRef, dest_dir: str, prefix: str = "") -> PathInfo:
        """Build ``PathInfo`` for a Jira ref.

        Args:
            ref: Parsed Jira reference.
            dest_dir: Output directory.
            prefix: Optional filename/wikilink prefix (e.g. ``"Wiki___Items___"``).
                Uses ``___`` as the separator in filenames and ``/`` in wikilinks.

        Returns:
            Computed path info.
        """
        wikilink_ns = prefix.replace("___", "/") if prefix else ""
        file_prefix = f"{dest_dir}/{prefix}{ref.endpoint}___{ref.key}"
        wikilink_prefix = f"{wikilink_ns}{ref.endpoint}/{ref.key}"
        return cls(
            file_prefix=file_prefix,
            file_sep="___",
            wikilink_prefix=wikilink_prefix,
            wikilink_sep="/",
        )

    @classmethod
    def from_ref(cls, ref: GitHubRef | JiraRef, dest_dir: str, prefix: str = "") -> PathInfo:
        """Dispatch to ``from_github`` or ``from_jira``.

        Args:
            ref: A GitHub or Jira reference.
            dest_dir: Output directory.
            prefix: Optional filename/wikilink prefix.

        Returns:
            Computed path info.
        """
        if isinstance(ref, GitHubRef):
            return cls.from_github(ref, dest_dir, prefix=prefix)
        return cls.from_jira(ref, dest_dir, prefix=prefix)


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
    #: Issue/PR creation day ``YYYY-MM-DD`` (from upstream API).
    created_at: str = ""
    #: Scheduling start day ``YYYY-MM-DD`` (e.g. assignment or PR creation).
    start_date: str = ""
    #: Raw upstream priority name (e.g. Jira ``"Major"``); empty for GitHub.
    priority: str = ""
    #: Computed due day ``YYYY-MM-DD`` (e.g. 1 week after last user comment or @mention).
    due_date: str = ""
    #: True when the ball is in the user's court (unanswered @mention or unactioned assignment).
    needinfo: bool = False
    #: False when needinfo heuristic was ambiguous and should be refined by LLM.
    needinfo_confident: bool = True


# ---------------------------------------------------------------------------
# NoteTags — structured tag data
# ---------------------------------------------------------------------------


class NoteTags(BaseModel):
    """Structured tag data for a note.

    Holds the raw tag facets (source, kind, org/repo).
    """

    source: Literal["github", "jira"]
    kind: str
    org_repo: str = ""

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
    "md": ("agent", "note"),
    "note": ("agent", ""),
    "agent": ("", "note"),
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

    def to_string(self, kind: FileKind) -> str:
        """Render the header as a string for the given file kind.

        Args:
            kind: Which file in the triplet (md, note, agent).

        Returns:
            Rendered header string.
        """
        lines = [f"# {self.title}", "", self.url, ""]
        if kind in ("md", "agent"):
            meta_parts = []
            if kind == "agent":
                meta_parts.append(f"**Type:** {self.note_type}")
            meta_parts.extend(
                [
                    f"**Status:** {self.status}",
                    f"**Author:** {self.author}" if kind == "agent" else "",
                    f"**Created:** {self.created}" if kind == "agent" else "",
                ]
            )
            meta_parts = [p for p in meta_parts if p]
            if kind == "agent":
                lines.append(" | ".join(meta_parts))
                lines.append("")
        return "\n".join(lines)

    @classmethod
    def from_content(
        cls,
        content: NoteContent,
        paths: PathInfo,
        kind: FileKind,
    ) -> NoteHeader:
        """Build a ``NoteHeader`` from content and path info.

        Args:
            content: Fetched note content.
            paths: Computed path info.
            kind: Which file in the triplet (md, note, agent).

        Returns:
            Populated header.
        """
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

    def to_string(self, kind: FileKind) -> str:
        """Render the body as a string for the given file kind.

        Args:
            kind: Which file in the triplet (md, note, agent).

        Returns:
            Rendered body string.
        """
        if kind == "md":
            return self._to_md()
        if kind == "note":
            return self._to_note()
        return self._to_agent()

    def _to_md(self) -> str:
        parts = ["## Description", "", self.description, "", "## Comments", ""]
        for comment in self.comments:
            parts.append(f"### @{comment.author} ({comment.date})")
            parts.extend(["", comment.body, ""])
        for section in self.sections:
            parts.append(f"## {section.heading}")
            parts.extend(["", section.content, ""])
        return "\n".join(parts)

    def _to_note(self) -> str:
        parts: list[str] = []
        for section in self.sections:
            parts.append(f"## {section.heading}")
            parts.extend(["", section.content, ""] if section.content else [""])
        return "\n".join(parts)

    def _to_agent(self) -> str:
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
            kind: Which file in the triplet (md, note, agent).

        Returns:
            Populated body.
        """
        if kind == "md":
            sections: list[Section] = []
            gh_url = content.extra.get("github_url")
            if gh_url and isinstance(gh_url, str):
                gh_match = _GH_URL_RE.match(gh_url)
                if gh_match:
                    wl = (
                        f"github.com/{gh_match['org']}/{gh_match['repo']}"
                        f"/{gh_match['url_type']}/{gh_match['number']}"
                    )
                    sections.append(
                        Section(
                            heading="GitHub PR",
                            content=f"[{gh_url}]({gh_url})\n[[{wl}]]",
                        ),
                    )
            sections.append(
                Section(
                    heading="Key Discussion Points",
                    content="<!-- summarize the above comments here -->",
                ),
            )
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
