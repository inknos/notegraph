#!/usr/bin/env bash
set -euo pipefail

DEFAULT_DIR="$HOME/Documents/Logseq/Work/pages"

usage() {
  echo "Usage: gh-note.sh [-d <dir>] [--check] [--md-only] <github-url>"
  echo "  -d <dir>    Target directory (default: $DEFAULT_DIR)"
  echo "  --check     Print JSON with file paths and existence status, then exit"
  echo "  --md-only   Only create the .md file (skip note and cursor)"
  echo "  e.g. gh-note.sh https://github.com/containers/podman/pull/24126"
  echo "  e.g. gh-note.sh --check https://github.com/containers/podman/pull/24126"
  exit 1
}

# Sets: org, repo, url_type, number, gh_cmd, yaml_type
parse_github_url() {
  local url="$1"
  if [[ "$url" =~ ^https://github\.com/([^/]+)/([^/]+)/(issues|pull)/([0-9]+) ]]; then
    org="${BASH_REMATCH[1]}"
    repo="${BASH_REMATCH[2]}"
    url_type="${BASH_REMATCH[3]}"
    number="${BASH_REMATCH[4]}"
  else
    echo "Error: URL does not match https://github.com/{org}/{repo}/{issues|pull}/{number}" >&2
    return 1
  fi

  if [[ "$url_type" == "pull" ]]; then
    gh_cmd="pr"
    yaml_type="pull_request"
  else
    gh_cmd="issue"
    yaml_type="issue"
  fi
}

# Sets: repo_root, dest_dir, file_prefix, wikilink_prefix, file_sep, wikilink_sep,
#       md_path, note_path, cursor_path
# Requires: org, repo, url_type, number (from parse_github_url)
compute_gh_paths() {
  local custom_dir="$1"
  if [[ -n "$custom_dir" ]]; then
    repo_root="$(cd "$custom_dir" && pwd)"
    dest_dir="${repo_root}"
    local page_ns="github.com___${org}___${repo}___${url_type}"
    file_prefix="${dest_dir}/${page_ns}___${number}"
    wikilink_prefix="github.com/${org}/${repo}/${url_type}/${number}"
    file_sep="___"
    wikilink_sep="/"
  else
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    repo_root="$(cd "$script_dir/.." && pwd)"
    dest_dir="${repo_root}/notes/github.com/${org}/${repo}/${url_type}"
    file_prefix="${dest_dir}/${number}"
    wikilink_prefix="${number}"
    file_sep="-"
    wikilink_sep="-"
  fi

  md_path="${file_prefix}.md"
  note_path="${file_prefix}${file_sep}note.md"
  cursor_path="${file_prefix}${file_sep}cursor.yaml"
}

# Pipe filter: replaces bare #NNN refs with wikilinks.
# Requires: org, repo (from parse_github_url)
expand_hash_refs() {
  sed -E "s/(^|[^[&])#([0-9]+)/\1[[github.com\/${org}\/${repo}\/issues\/\2]]/g"
}

map_gh_state() {
  local raw="$1"
  case "$raw" in
    OPEN)   echo "open"   ;;
    CLOSED) echo "closed" ;;
    MERGED) echo "merged" ;;
    *)      echo "$raw" | tr '[:upper:]' '[:lower:]' ;;
  esac
}

write_if_missing() {
  local path="$1"
  local content="$2"
  if [[ -f "$path" ]]; then
    echo "  skip (exists): $path"
  else
    printf '%s\n' "$content" > "$path"
    echo "  created:       $path"
  fi
}

main() {
  local custom_dir="$DEFAULT_DIR"
  local check_only=false
  local md_only=false

  local args=()
  for arg in "$@"; do
    case "$arg" in
      --check)   check_only=true ;;
      --md-only) md_only=true ;;
      *)         args+=("$arg") ;;
    esac
  done
  set -- "${args[@]}"

  OPTIND=1
  while getopts ":d:" opt; do
    case $opt in
      d) custom_dir="$OPTARG" ;;
      *) usage ;;
    esac
  done
  shift $((OPTIND - 1))

  [[ $# -ne 1 ]] && usage

  local url="$1"

  parse_github_url "$url"
  compute_gh_paths "$custom_dir"

  # ------------------------------------------------------------------
  # --check: return JSON with paths and existence, no network calls
  # ------------------------------------------------------------------
  if [[ "$check_only" == true ]]; then
    exists() { [[ -f "$1" ]] && echo true || echo false; }
    printf '{"md":{"path":"%s","exists":%s},"note":{"path":"%s","exists":%s},"cursor":{"path":"%s","exists":%s}}\n' \
      "$md_path" "$(exists "$md_path")" \
      "$note_path" "$(exists "$note_path")" \
      "$cursor_path" "$(exists "$cursor_path")"
    exit 0
  fi

  # ------------------------------------------------------------------
  # Fetch data from GitHub
  # ------------------------------------------------------------------
  local json_fields="title,url,state,author,createdAt,body,comments"
  [[ "$gh_cmd" == "pr" ]] && json_fields="${json_fields},mergedAt"

  local json
  json=$(gh "$gh_cmd" view "$url" --json "$json_fields")

  local title gh_url author created body
  title=$(echo "$json"   | jq -r '.title')
  gh_url=$(echo "$json"  | jq -r '.url')
  author=$(echo "$json"  | jq -r '.author.login')
  created=$(echo "$json" | jq -r '.createdAt[:10]')
  body=$(echo "$json"    | jq -r '.body // ""')

  body=$(echo "$body" | expand_hash_refs)

  local raw_state status
  raw_state=$(echo "$json" | jq -r '.state')
  status=$(map_gh_state "$raw_state")

  mkdir -p "$dest_dir"

  # ------------------------------------------------------------------
  # 1. cursor.yaml (skipped in --md-only mode)
  # ------------------------------------------------------------------
  if [[ "$md_only" == false ]]; then
    local yaml_content="title: \"${title}\"
url: \"${gh_url}\"
type: ${yaml_type}
status: ${status}
author: \"${author}\"
created: \"${created}\""

    write_if_missing "$cursor_path" "$yaml_content"
  fi

  # ------------------------------------------------------------------
  # 2. {number}.md (summary + raw comments)
  # ------------------------------------------------------------------
  local comments_section=""
  local comment_count
  comment_count=$(echo "$json" | jq '.comments | length')
  if [[ "$comment_count" -gt 0 ]]; then
    comments_section=$(echo "$json" | jq -r '
      .comments[] |
      "### @\(.author.login) (\(.createdAt[:10]))\n\n\(.body)\n"
    ')
    comments_section=$(echo "$comments_section" | expand_hash_refs)
  fi

  local md_content="# ${title}

${gh_url}

## Description

${body}

## Comments

${comments_section}
## Key Discussion Points

<!-- summarize the above comments here -->

---

[[${wikilink_prefix}${wikilink_sep}cursor]]
[[${wikilink_prefix}${wikilink_sep}note]]"

  write_if_missing "$md_path" "$md_content"

  # ------------------------------------------------------------------
  # 3. note.md (personal notes skeleton, skipped in --md-only mode)
  # ------------------------------------------------------------------
  if [[ "$md_only" == false ]]; then
    local note_content="# ${title}

## Notes

## TODOs

## Related

---

[[${wikilink_prefix}${wikilink_sep}cursor]]
[[${wikilink_prefix}]]"

    write_if_missing "$note_path" "$note_content"
  fi

  # ------------------------------------------------------------------
  # 4. Add link to ## Github Issues section in index.md (default workspace only)
  # ------------------------------------------------------------------
  if [[ -n "$custom_dir" ]]; then
    echo "Done."
    exit 0
  fi

  local index_file="${repo_root}/index.md"
  local index_link="notes/github.com/${org}/${repo}/${url_type}/${number}"

  if [[ -f "$index_file" ]] && ! grep -qF "[[${index_link}]]" "$index_file"; then
    local section_line
    section_line=$(grep -n '^## Github Issues' "$index_file" | head -1 | cut -d: -f1)

    if [[ -n "$section_line" ]]; then
      local insert_after="$section_line"
      local line_num=$((section_line + 1))
      local total_lines
      total_lines=$(wc -l < "$index_file")
      while [[ $line_num -le $total_lines ]]; do
        local line_content
        line_content=$(sed -n "${line_num}p" "$index_file")
        if [[ "$line_content" =~ ^-\ \[\[ ]]; then
          insert_after=$line_num
        elif [[ -n "$line_content" && ! "$line_content" =~ ^[[:space:]]*$ ]]; then
          break
        fi
        line_num=$((line_num + 1))
      done

      sed -i "${insert_after}a\\
- [[${index_link}]]" "$index_file"

      printf '\n[%s]: %s.md "%s"\n' "$index_link" "$index_link" "$title" >> "$index_file"

      echo "  index.md:      added link for ${index_link}"
    else
      echo "  index.md:      no '## Github Issues' section found, skipped"
    fi
  else
    if [[ ! -f "$index_file" ]]; then
      echo "  index.md:      file not found, skipped"
    else
      echo "  index.md:      link already present, skipped"
    fi
  fi

  echo "Done."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
