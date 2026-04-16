# TODO

## Jira Epic handling

`notegraph fetch --source jira` only handles a single issue. Add Epic
support: detect Epic issue type, query children via JQL
(`parent = <KEY>`), and write files per child with the same
closed/open semantics (md-only for closed children, full triplet for
open children).

## Closed issue skip

`notegraph fetch --source jira` doesn't check for closed status and
writes files regardless. Add an early exit (or at least a warning)
when the fetched issue is Closed and not an Epic.
