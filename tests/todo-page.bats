#!/usr/bin/env bats
# shellcheck disable=SC2034,SC2154

setup() {
  load test_helper
  setup_tmpdir
  source_script todo-page.sh
}

teardown() {
  teardown_tmpdir
}

# -----------------------------------------------------------------------
# parse_worktodo_sections
# -----------------------------------------------------------------------

@test "parse_worktodo_sections: empty when file does not exist" {
  parse_worktodo_sections "$TEST_TMPDIR/nonexistent.md"
  [ ${#focus_links[@]} -eq 0 ]
  [ ${#backlog_links[@]} -eq 0 ]
}

@test "parse_worktodo_sections: extracts Focus links" {
  cat > "$TEST_TMPDIR/worktodo.md" <<'EOF'
# Worktodo

## Focus

- [[github.com/org/repo/pull/1]] Some PR (**OPEN**)
- [[github.com/org/repo/issues/2]] Some issue (**OPEN**)

## Backlog

## Incoming
EOF

  parse_worktodo_sections "$TEST_TMPDIR/worktodo.md"
  [ ${#focus_links[@]} -eq 2 ]
  [ "${focus_links[0]}" = "github.com/org/repo/pull/1" ]
  [ "${focus_links[1]}" = "github.com/org/repo/issues/2" ]
  [ ${#backlog_links[@]} -eq 0 ]
}

@test "parse_worktodo_sections: extracts Backlog links" {
  cat > "$TEST_TMPDIR/worktodo.md" <<'EOF'
# Worktodo

## Focus

## Backlog

- [[test.atlassian.net/RUN-100]] Jira ticket (**In Progress**)

## Incoming
EOF

  parse_worktodo_sections "$TEST_TMPDIR/worktodo.md"
  [ ${#focus_links[@]} -eq 0 ]
  [ ${#backlog_links[@]} -eq 1 ]
  [ "${backlog_links[0]}" = "test.atlassian.net/RUN-100" ]
}

@test "parse_worktodo_sections: ignores Incoming links" {
  cat > "$TEST_TMPDIR/worktodo.md" <<'EOF'
# Worktodo

## Focus

- [[a/1]] F1

## Backlog

- [[b/2]] B1

## Incoming

- [[c/3]] I1
- [[d/4]] I2
EOF

  parse_worktodo_sections "$TEST_TMPDIR/worktodo.md"
  [ ${#focus_links[@]} -eq 1 ]
  [ "${focus_links[0]}" = "a/1" ]
  [ ${#backlog_links[@]} -eq 1 ]
  [ "${backlog_links[0]}" = "b/2" ]
}

@test "parse_worktodo_sections: handles mixed sections correctly" {
  cat > "$TEST_TMPDIR/worktodo.md" <<'EOF'
# Worktodo

*Updated: 2025-04-01*

## Focus

- [[link/f1]] Focus item 1 (**OPEN**)
- [[link/f2]] Focus item 2 (**OPEN**)

## Backlog

- [[link/b1]] Backlog item 1 (**In Progress**)

## Incoming

- [[link/i1]] Incoming 1 (**OPEN**)
EOF

  parse_worktodo_sections "$TEST_TMPDIR/worktodo.md"
  [ ${#focus_links[@]} -eq 2 ]
  [ "${focus_links[0]}" = "link/f1" ]
  [ "${focus_links[1]}" = "link/f2" ]
  [ ${#backlog_links[@]} -eq 1 ]
  [ "${backlog_links[0]}" = "link/b1" ]
}

# -----------------------------------------------------------------------
# write_worktodo
# -----------------------------------------------------------------------

@test "write_worktodo: produces correct section structure" {
  declare -A item_lines
  item_lines["link/1"]="- [[link/1]] Item one (**OPEN**)"
  item_lines["link/2"]="- [[link/2]] Item two (**OPEN**)"
  item_lines["link/3"]="- [[link/3]] Item three (**OPEN**)"

  focus_links=("link/1")
  backlog_links=("link/2")
  all_links_ordered=("link/1" "link/2" "link/3")

  local outfile="$TEST_TMPDIR/out.md"
  write_worktodo "$outfile"

  [ -f "$outfile" ]

  # Check section headers
  run grep -c '^## Focus$' "$outfile"
  [ "$output" = "1" ]
  run grep -c '^## Backlog$' "$outfile"
  [ "$output" = "1" ]
  run grep -c '^## Incoming$' "$outfile"
  [ "$output" = "1" ]
  run grep -c '^# Worktodo$' "$outfile"
  [ "$output" = "1" ]
}

@test "write_worktodo: places items in correct sections" {
  declare -A item_lines
  item_lines["f/1"]="- [[f/1]] focus item"
  item_lines["b/1"]="- [[b/1]] backlog item"
  item_lines["i/1"]="- [[i/1]] incoming item"

  focus_links=("f/1")
  backlog_links=("b/1")
  all_links_ordered=("f/1" "b/1" "i/1")

  local outfile="$TEST_TMPDIR/out.md"
  write_worktodo "$outfile"

  # Focus item appears between ## Focus and ## Backlog
  local focus_pos backlog_pos incoming_pos
  focus_pos=$(grep -n '^## Focus$' "$outfile" | cut -d: -f1)
  backlog_pos=$(grep -n '^## Backlog$' "$outfile" | cut -d: -f1)
  incoming_pos=$(grep -n '^## Incoming$' "$outfile" | cut -d: -f1)

  focus_item_line=$(grep -n 'focus item' "$outfile" | cut -d: -f1)
  backlog_item_line=$(grep -n 'backlog item' "$outfile" | cut -d: -f1)
  incoming_item_line=$(grep -n 'incoming item' "$outfile" | cut -d: -f1)

  [ "$focus_item_line" -gt "$focus_pos" ]
  [ "$focus_item_line" -lt "$backlog_pos" ]
  [ "$backlog_item_line" -gt "$backlog_pos" ]
  [ "$backlog_item_line" -lt "$incoming_pos" ]
  [ "$incoming_item_line" -gt "$incoming_pos" ]
}

@test "write_worktodo: does not duplicate placed items in Incoming" {
  declare -A item_lines
  item_lines["a/1"]="- [[a/1]] already placed"
  item_lines["a/2"]="- [[a/2]] new item"

  focus_links=("a/1")
  backlog_links=()
  all_links_ordered=("a/1" "a/2")

  local outfile="$TEST_TMPDIR/out.md"
  write_worktodo "$outfile"

  # "already placed" should appear once (in Focus), not in Incoming
  run grep -c 'already placed' "$outfile"
  [ "$output" = "1" ]

  # "new item" should appear in Incoming
  run grep -c 'new item' "$outfile"
  [ "$output" = "1" ]
}

@test "write_worktodo: drops stale focus items not in item_lines" {
  declare -A item_lines
  item_lines["a/1"]="- [[a/1]] still active"

  focus_links=("a/1" "a/stale")
  backlog_links=()
  all_links_ordered=("a/1")

  local outfile="$TEST_TMPDIR/out.md"
  write_worktodo "$outfile"

  run grep -c 'still active' "$outfile"
  [ "$output" = "1" ]

  # stale link has no item_lines entry, so nothing gets printed for it
  run grep -c 'a/stale' "$outfile"
  [ "$output" = "0" ]
}

@test "write_worktodo: includes Updated date" {
  declare -A item_lines
  focus_links=()
  backlog_links=()
  all_links_ordered=()

  local outfile="$TEST_TMPDIR/out.md"
  write_worktodo "$outfile"

  run grep -c 'Updated:' "$outfile"
  [ "$output" = "1" ]
}

# -----------------------------------------------------------------------
# Argument parsing (subprocess)
# -----------------------------------------------------------------------

@test "main: rejects no arguments" {
  run "$SCRIPT_DIR/todo-page.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"at least one --org or --repo"* ]] || [[ "$output" == *"Usage:"* ]]
}

@test "main: rejects unknown option" {
  run "$SCRIPT_DIR/todo-page.sh" --bogus
  [ "$status" -ne 0 ]
  [[ "$output" == *"Unknown option"* ]]
}

@test "main: rejects --org without value" {
  run "$SCRIPT_DIR/todo-page.sh" --org
  [ "$status" -ne 0 ]
}
