#!/usr/bin/env bats
# shellcheck disable=SC2034,SC2154

setup() {
  load test_helper
  setup_tmpdir
  source_script gh-note.sh
}

teardown() {
  teardown_tmpdir
}

# -----------------------------------------------------------------------
# parse_github_url
# -----------------------------------------------------------------------

@test "parse_github_url: parses a PR URL" {
  parse_github_url "https://github.com/containers/podman/pull/24126"
  [ "$org"       = "containers" ]
  [ "$repo"      = "podman" ]
  [ "$url_type"  = "pull" ]
  [ "$number"    = "24126" ]
  [ "$gh_cmd"    = "pr" ]
  [ "$yaml_type" = "pull_request" ]
}

@test "parse_github_url: parses an issue URL" {
  parse_github_url "https://github.com/openshift/origin/issues/999"
  [ "$org"       = "openshift" ]
  [ "$repo"      = "origin" ]
  [ "$url_type"  = "issues" ]
  [ "$number"    = "999" ]
  [ "$gh_cmd"    = "issue" ]
  [ "$yaml_type" = "issue" ]
}

@test "parse_github_url: rejects invalid URL" {
  run parse_github_url "https://example.com/not/a/github/url"
  [ "$status" -ne 0 ]
  [[ "$output" == *"does not match"* ]]
}

@test "parse_github_url: rejects URL without number" {
  run parse_github_url "https://github.com/org/repo/pull/"
  [ "$status" -ne 0 ]
}

# -----------------------------------------------------------------------
# compute_gh_paths (with custom_dir)
# -----------------------------------------------------------------------

@test "compute_gh_paths: custom dir produces ___-separated paths" {
  parse_github_url "https://github.com/containers/podman/pull/24126"
  compute_gh_paths "$TEST_TMPDIR"

  [ "$dest_dir"        = "$TEST_TMPDIR" ]
  [ "$file_sep"        = "___" ]
  [ "$wikilink_sep"    = "/" ]
  [ "$wikilink_prefix" = "github.com/containers/podman/pull/24126" ]
  [ "$md_path"         = "$TEST_TMPDIR/github.com___containers___podman___pull___24126.md" ]
  [ "$note_path"       = "$TEST_TMPDIR/github.com___containers___podman___pull___24126___note.md" ]
  [ "$cursor_path"     = "$TEST_TMPDIR/github.com___containers___podman___pull___24126___cursor.md" ]
}

@test "compute_gh_paths: issue URL paths" {
  parse_github_url "https://github.com/org/repo/issues/42"
  compute_gh_paths "$TEST_TMPDIR"

  [ "$md_path"     = "$TEST_TMPDIR/github.com___org___repo___issues___42.md" ]
  [ "$note_path"   = "$TEST_TMPDIR/github.com___org___repo___issues___42___note.md" ]
  [ "$cursor_path" = "$TEST_TMPDIR/github.com___org___repo___issues___42___cursor.md" ]
}

# -----------------------------------------------------------------------
# expand_hash_refs
# -----------------------------------------------------------------------

@test "expand_hash_refs: replaces bare #NNN with wikilink" {
  org="containers"
  repo="podman"
  result=$(echo "See #1234 for details" | expand_hash_refs)
  [ "$result" = "See [[github.com/containers/podman/issues/1234]] for details" ]
}

@test "expand_hash_refs: replaces multiple refs" {
  org="myorg"
  repo="myrepo"
  result=$(echo "Fixes #10 and #20" | expand_hash_refs)
  [ "$result" = "Fixes [[github.com/myorg/myrepo/issues/10]] and [[github.com/myorg/myrepo/issues/20]]" ]
}

@test "expand_hash_refs: does not replace already-linked refs" {
  org="o"
  repo="r"
  input="See [[github.com/o/r/issues/5]] already"
  result=$(echo "$input" | expand_hash_refs)
  [ "$result" = "$input" ]
}

@test "expand_hash_refs: does not replace HTML entities like &#123;" {
  org="o"
  repo="r"
  result=$(echo "char &#123; here" | expand_hash_refs)
  [ "$result" = "char &#123; here" ]
}

@test "expand_hash_refs: handles ref at start of line" {
  org="a"
  repo="b"
  result=$(echo "#99 is the issue" | expand_hash_refs)
  [ "$result" = "[[github.com/a/b/issues/99]] is the issue" ]
}

# -----------------------------------------------------------------------
# map_gh_state
# -----------------------------------------------------------------------

@test "map_gh_state: OPEN -> open" {
  result=$(map_gh_state "OPEN")
  [ "$result" = "open" ]
}

@test "map_gh_state: CLOSED -> closed" {
  result=$(map_gh_state "CLOSED")
  [ "$result" = "closed" ]
}

@test "map_gh_state: MERGED -> merged" {
  result=$(map_gh_state "MERGED")
  [ "$result" = "merged" ]
}

@test "map_gh_state: unknown state lowercased" {
  result=$(map_gh_state "DRAFT")
  [ "$result" = "draft" ]
}

# -----------------------------------------------------------------------
# write_if_missing
# -----------------------------------------------------------------------

@test "write_if_missing: creates file when absent" {
  local f="$TEST_TMPDIR/newfile.txt"
  run write_if_missing "$f" "hello world"
  [ "$status" -eq 0 ]
  [[ "$output" == *"created"* ]]
  [ -f "$f" ]
  [ "$(cat "$f")" = "hello world" ]
}

@test "write_if_missing: skips when file exists" {
  local f="$TEST_TMPDIR/existing.txt"
  echo "original" > "$f"
  run write_if_missing "$f" "new content"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skip (exists)"* ]]
  [ "$(cat "$f")" = "original" ]
}

# -----------------------------------------------------------------------
# --check mode (runs script as subprocess)
# -----------------------------------------------------------------------

@test "--check: returns valid JSON with exists=false for missing files" {
  run "$SCRIPT_DIR/gh-note.sh" --check -d "$TEST_TMPDIR" \
      "https://github.com/containers/podman/pull/24126"
  [ "$status" -eq 0 ]

  md_exists=$(echo "$output" | jq -r '.md.exists')
  note_exists=$(echo "$output" | jq -r '.note.exists')
  cursor_exists=$(echo "$output" | jq -r '.cursor.exists')
  [ "$md_exists"     = "false" ]
  [ "$note_exists"   = "false" ]
  [ "$cursor_exists" = "false" ]
}

@test "--check: returns exists=true when md file is present" {
  parse_github_url "https://github.com/containers/podman/pull/24126"
  compute_gh_paths "$TEST_TMPDIR"
  echo "content" > "$md_path"

  run "$SCRIPT_DIR/gh-note.sh" --check -d "$TEST_TMPDIR" \
      "https://github.com/containers/podman/pull/24126"
  [ "$status" -eq 0 ]
  md_exists=$(echo "$output" | jq -r '.md.exists')
  [ "$md_exists" = "true" ]
}

@test "--check: paths contain correct org/repo/number" {
  run "$SCRIPT_DIR/gh-note.sh" --check -d "$TEST_TMPDIR" \
      "https://github.com/myorg/myrepo/issues/42"
  [ "$status" -eq 0 ]

  md_path_out=$(echo "$output" | jq -r '.md.path')
  [[ "$md_path_out" == *"myorg"* ]]
  [[ "$md_path_out" == *"myrepo"* ]]
  [[ "$md_path_out" == *"issues"* ]]
  [[ "$md_path_out" == *"42"* ]]
}

@test "--check: rejects bad URL" {
  run "$SCRIPT_DIR/gh-note.sh" --check -d "$TEST_TMPDIR" "https://example.com/nope"
  [ "$status" -ne 0 ]
}
