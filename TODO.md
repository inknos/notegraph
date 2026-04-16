# TODO

## Jira Epic handling

`jira-note.sh` queries child issues for Epics and creates files for each:
- md-only for closed children
- full triplet (md + note + cursor) for open children

`notegraph fetch --source jira` only handles a single issue. Add Epic
support: detect Epic issue type, query children via JQL
(`parent = <KEY>`), and write files per child with the same
closed/open semantics.

## Closed issue skip

`jira-note.sh` exits without creating files when a non-Epic issue has
status Closed. `notegraph fetch --source jira` doesn't check for this
and writes files regardless. Add an early exit (or at least a warning)
when the fetched issue is Closed and not an Epic.
