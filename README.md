# notegraph

Tools for Jira, GitHub issues, and Logseq notes.

**Documentation:** https://inknos.github.io/notegraph/

## Install

```bash
uv sync --all-extras
```

## Examples

```bash
notegraph fetch --source github --check --json https://github.com/org/repo/pull/1
notegraph fetch --source jira RUN-1234
```

Optional Cursor rules (requires `JIRA_ENDPOINT`):

```bash
make install JIRA_ENDPOINT=yourorg.atlassian.net
```
