#!/usr/bin/env bash
# Shared test helper for all bats test files.
# Source this from setup() via: load test_helper

SCRIPT_DIR="$(cd "$(dirname "${BATS_TEST_FILENAME}")/../scripts" && pwd)"

export JIRA_ENDPOINT="test.atlassian.net"

setup_tmpdir() {
  TEST_TMPDIR="$(mktemp -d)"
}

teardown_tmpdir() {
  [[ -d "${TEST_TMPDIR:-}" ]] && rm -rf "$TEST_TMPDIR"
}

# Source a script (functions only, main() won't run due to BASH_SOURCE guard).
# Usage: source_script gh-note.sh
source_script() {
  # shellcheck disable=SC1090
  source "${SCRIPT_DIR}/$1"
}
