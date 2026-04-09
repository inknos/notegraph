#!/usr/bin/env bats
# shellcheck disable=SC2034,SC2154

setup() {
  load test_helper
  setup_tmpdir
  source_script jira-note.sh
  dest_dir="$TEST_TMPDIR"
}

teardown() {
  teardown_tmpdir
}

# -----------------------------------------------------------------------
# normalize_issue_key
# -----------------------------------------------------------------------

@test "normalize_issue_key: uppercases a plain key" {
  result=$(normalize_issue_key "run-3555")
  [ "$result" = "RUN-3555" ]
}

@test "normalize_issue_key: passes through already-uppercase key" {
  result=$(normalize_issue_key "RUN-3555")
  [ "$result" = "RUN-3555" ]
}

@test "normalize_issue_key: strips browse URL" {
  result=$(normalize_issue_key "https://test.atlassian.net/browse/RUN-3555")
  [ "$result" = "RUN-3555" ]
}

@test "normalize_issue_key: strips browse URL and uppercases" {
  result=$(normalize_issue_key "https://jira.example.com/browse/FOO-123")
  [ "$result" = "FOO-123" ]
}

# -----------------------------------------------------------------------
# Path computation functions
# -----------------------------------------------------------------------

@test "file_prefix_for: builds correct prefix" {
  result=$(file_prefix_for "RUN-3555")
  [ "$result" = "$TEST_TMPDIR/test.atlassian.net___RUN-3555" ]
}

@test "wikilink_for: builds correct wikilink" {
  result=$(wikilink_for "RUN-3555")
  [ "$result" = "test.atlassian.net/RUN-3555" ]
}

@test "md_path_for: appends .md" {
  result=$(md_path_for "RUN-3555")
  [ "$result" = "$TEST_TMPDIR/test.atlassian.net___RUN-3555.md" ]
}

@test "note_path_for: appends ___note.md" {
  result=$(note_path_for "RUN-3555")
  [ "$result" = "$TEST_TMPDIR/test.atlassian.net___RUN-3555___note.md" ]
}

@test "cursor_path_for: appends ___cursor.yaml" {
  result=$(cursor_path_for "RUN-3555")
  [ "$result" = "$TEST_TMPDIR/test.atlassian.net___RUN-3555___cursor.yaml" ]
}

# -----------------------------------------------------------------------
# write_if_missing
# -----------------------------------------------------------------------

@test "write_if_missing: creates file when absent" {
  local f="$TEST_TMPDIR/new.txt"
  run write_if_missing "$f" "data"
  [ "$status" -eq 0 ]
  [[ "$output" == *"created"* ]]
  [ "$(cat "$f")" = "data" ]
}

@test "write_if_missing: skips existing file" {
  local f="$TEST_TMPDIR/old.txt"
  echo "keep" > "$f"
  run write_if_missing "$f" "replace"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skip (exists)"* ]]
  [ "$(cat "$f")" = "keep" ]
}

# -----------------------------------------------------------------------
# write_always
# -----------------------------------------------------------------------

@test "write_always: creates new file" {
  local f="$TEST_TMPDIR/fresh.txt"
  run write_always "$f" "content"
  [ "$status" -eq 0 ]
  [ "$(cat "$f")" = "content" ]
}

@test "write_always: overwrites existing file" {
  local f="$TEST_TMPDIR/overwrite.txt"
  echo "old" > "$f"
  run write_always "$f" "new"
  [ "$status" -eq 0 ]
  [ "$(cat "$f")" = "new" ]
}

# -----------------------------------------------------------------------
# build_comments
# -----------------------------------------------------------------------

@test "build_comments: empty comments array" {
  local json='{"comment":{"comments":[]}}'
  result=$(build_comments "$json")
  [ -z "$result" ]
}

@test "build_comments: single comment formatted correctly" {
  local json='{"comment":{"comments":[{"author":{"displayName":"Alice"},"created":"2025-01-15T10:00:00.000+0000","body":"Looks good"}]}}'
  result=$(build_comments "$json")
  [[ "$result" == *"### Alice (2025-01-15)"* ]]
  [[ "$result" == *"Looks good"* ]]
}

@test "build_comments: multiple comments" {
  local json='{"comment":{"comments":[
    {"author":{"displayName":"Alice"},"created":"2025-01-15T10:00:00.000+0000","body":"First"},
    {"author":{"displayName":"Bob"},"created":"2025-01-16T10:00:00.000+0000","body":"Second"}
  ]}}'
  result=$(build_comments "$json")
  [[ "$result" == *"### Alice"* ]]
  [[ "$result" == *"### Bob"* ]]
  [[ "$result" == *"First"* ]]
  [[ "$result" == *"Second"* ]]
}

# -----------------------------------------------------------------------
# --check mode (subprocess)
# -----------------------------------------------------------------------

@test "--check: returns valid JSON with exists=false" {
  run "$SCRIPT_DIR/jira-note.sh" --check -d "$TEST_TMPDIR" "RUN-3555"
  [ "$status" -eq 0 ]

  md_exists=$(echo "$output" | jq -r '.md.exists')
  note_exists=$(echo "$output" | jq -r '.note.exists')
  cursor_exists=$(echo "$output" | jq -r '.cursor.exists')
  [ "$md_exists"     = "false" ]
  [ "$note_exists"   = "false" ]
  [ "$cursor_exists" = "false" ]
}

@test "--check: returns exists=true for existing files" {
  local md_p
  md_p=$(md_path_for "RUN-3555")
  echo "content" > "$md_p"

  run "$SCRIPT_DIR/jira-note.sh" --check -d "$TEST_TMPDIR" "RUN-3555"
  [ "$status" -eq 0 ]
  md_exists=$(echo "$output" | jq -r '.md.exists')
  [ "$md_exists" = "true" ]
}

@test "--check: normalizes lowercase key" {
  run "$SCRIPT_DIR/jira-note.sh" --check -d "$TEST_TMPDIR" "run-1234"
  [ "$status" -eq 0 ]
  md_path_out=$(echo "$output" | jq -r '.md.path')
  [[ "$md_path_out" == *"RUN-1234"* ]]
}

@test "--check: rejects missing argument" {
  run "$SCRIPT_DIR/jira-note.sh" --check -d "$TEST_TMPDIR"
  [ "$status" -ne 0 ]
}
