#!/usr/bin/env bash
set -euo pipefail

DEST_DIR="$HOME/Documents/Logseq/Work/pages"
JIRA_REPO="${JIRA_REPO:-$HOME/Documents/personal_projects/notegraph/jira}"
JIRA_ENDPOINT="${JIRA_ENDPOINT:-test.atlassian.net}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: todo-page.sh [--sync] [--org <org>]... [--repo <owner/repo>]..."
  echo "  --org <org>          Search all repos in a GitHub org (repeatable)"
  echo "  --repo <owner/repo>  Search a specific GitHub repo (repeatable)"
  echo "  --sync               Also create/refresh individual note pages via gh-note.sh / jira-note.sh"
  echo ""
  echo "At least one --org or --repo is required."
  echo ""
  echo "  e.g. todo-page.sh --org containers"
  echo "  e.g. todo-page.sh --org containers --repo myorg/some-tool --sync"
  exit 1
}

gh_search() {
  local kind="$1"  # issues or prs
  local scope_flag="$2"  # --owner or --repo
  local scope_val="$3"
  local extra_flags=("${@:4}")

  gh search "$kind" \
    "${extra_flags[@]}" \
    "$scope_flag" "$scope_val" \
    --state=open \
    --json url,title,repository,state,assignees,updatedAt \
    -L 100 2>/dev/null || true
}

jira_cmd() {
  (cd "$JIRA_REPO" && go run -tags gnome_keyring cmd/jira/main.go "$@" 2>/dev/null)
}

# Parses an existing worktodo.md and sets the global arrays:
#   focus_links   - wikilinks under ## Focus
#   backlog_links - wikilinks under ## Backlog
parse_worktodo_sections() {
  local file="$1"
  focus_links=()
  backlog_links=()

  [[ -f "$file" ]] || return 0

  local current_section=""
  local line
  while IFS= read -r line; do
    case "$line" in
      "## Focus")    current_section="focus" ;;
      "## Backlog")  current_section="backlog" ;;
      "## Incoming") current_section="incoming" ;;
      "## "*)        current_section="" ;;
    esac
    if [[ "$line" =~ ^-\ \[\[([^\]]+)\]\] ]]; then
      local wikilink="${BASH_REMATCH[1]}"
      case "$current_section" in
        focus)   focus_links+=("$wikilink") ;;
        backlog) backlog_links+=("$wikilink") ;;
      esac
    fi
  done < "$file"
}

# Writes worktodo.md from the item_lines map, focus_links, backlog_links,
# and all_links_ordered arrays.
# $1 = destination file path
write_worktodo() {
  local dest_file="$1"
  local today
  today=$(date +%Y-%m-%d)

  # Build lookup set for items already placed in Focus/Backlog
  declare -A placed_links
  local link
  for link in "${focus_links[@]+"${focus_links[@]}"}" "${backlog_links[@]+"${backlog_links[@]}"}"; do
    [[ -n "$link" ]] && placed_links["$link"]=1
  done

  {
    echo "# Worktodo"
    echo ""
    echo "*Updated: ${today}*"
    echo ""
    echo "## Focus"
    echo ""
    for link in "${focus_links[@]+"${focus_links[@]}"}"; do
      [[ -n "${item_lines[$link]:-}" ]] && echo "${item_lines[$link]}"
    done
    echo ""
    echo "## Backlog"
    echo ""
    for link in "${backlog_links[@]+"${backlog_links[@]}"}"; do
      [[ -n "${item_lines[$link]:-}" ]] && echo "${item_lines[$link]}"
    done
    echo ""
    echo "## Incoming"
    echo ""
    for link in "${all_links_ordered[@]}"; do
      if [[ -z "${placed_links[$link]:-}" && -n "${item_lines[$link]:-}" ]]; then
        echo "${item_lines[$link]}"
      fi
    done
  } > "$dest_file"
}

main() {
  local sync=false
  local orgs=()
  local repos=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --sync)
        sync=true
        shift
        ;;
      --org)
        [[ $# -lt 2 ]] && usage
        orgs+=("$2")
        shift 2
        ;;
      --repo)
        [[ $# -lt 2 ]] && usage
        repos+=("$2")
        shift 2
        ;;
      -h|--help)
        usage
        ;;
      *)
        echo "Unknown option: $1" >&2
        usage
        ;;
    esac
  done

  if [[ ${#orgs[@]} -eq 0 && ${#repos[@]} -eq 0 ]]; then
    echo "Error: at least one --org or --repo is required." >&2
    usage
  fi

  # -------------------------------------------------------------------
  # Resolve GitHub username
  # -------------------------------------------------------------------
  local gh_user
  gh_user=$(gh api user --jq '.login')
  echo "GitHub user: $gh_user"

  # -------------------------------------------------------------------
  # GitHub: collect issues and PRs into a temp file
  # -------------------------------------------------------------------
  local gh_items
  gh_items=$(mktemp)
  trap 'rm -f "$gh_items"' EXIT

  local org
  for org in "${orgs[@]}"; do
    echo "Searching GitHub org: $org ..."
    {
      gh_search issues --owner "$org" --involves="$gh_user"
      gh_search prs    --owner "$org" --involves="$gh_user"
      gh_search prs    --owner "$org" --review-requested="$gh_user"
    } >> "$gh_items"
  done

  local repo
  for repo in "${repos[@]}"; do
    echo "Searching GitHub repo: $repo ..."
    {
      gh_search issues --repo "$repo" --involves="$gh_user"
      gh_search prs    --repo "$repo" --involves="$gh_user"
      gh_search prs    --repo "$repo" --review-requested="$gh_user"
    } >> "$gh_items"
  done

  local gh_deduped
  gh_deduped=$(jq -s '
    [ .[][] ] | unique_by(.url)
    | group_by(.repository.nameWithOwner)
    | map(sort_by(.updatedAt) | reverse)
    | sort_by(.[0].updatedAt) | reverse
    | [.[][]]
  ' "$gh_items")

  local gh_count
  gh_count=$(echo "$gh_deduped" | jq 'length')
  echo "GitHub: $gh_count open items"

  # -------------------------------------------------------------------
  # Jira: collect assigned issues
  # -------------------------------------------------------------------
  local jira_login
  jira_login=$(grep '^login:' "$JIRA_REPO/.jira.d/config.yml" | awk '{print $2}')
  echo "Searching Jira (assignee = ${jira_login}) ..."
  local jira_raw
  jira_raw=$(jira_cmd list --query "assignee = '${jira_login}' AND status != Closed ORDER BY updated DESC" 2>/dev/null || true)

  local jira_keys=()
  if [[ -n "$jira_raw" ]]; then
    local line
    while IFS= read -r line; do
      local key
      key=$(echo "$line" | sed 's/:.*//' | tr -d '[:space:]')
      [[ -n "$key" ]] && jira_keys+=("$key")
    done <<< "$jira_raw"
  fi

  echo "Jira: ${#jira_keys[@]} open items"

  declare -A jira_summary_map
  declare -A jira_status_map

  local key
  for key in "${jira_keys[@]}"; do
    local fields
    fields=$(jira_cmd view "$key" --gjq 'fields' 2>/dev/null || true)
    if [[ -n "$fields" ]]; then
      jira_summary_map["$key"]=$(echo "$fields" | jq -r '.summary // ""')
      jira_status_map["$key"]=$(echo "$fields" | jq -r '.status.name // ""')
    else
      jira_summary_map["$key"]="(fetch failed)"
      jira_status_map["$key"]="unknown"
    fi
  done

  # -------------------------------------------------------------------
  # Build item map
  # -------------------------------------------------------------------
  declare -A item_lines
  declare -a all_links_ordered=()

  local wikilink line
  while IFS=$'\t' read -r wikilink line; do
    [[ -z "$wikilink" ]] && continue
    item_lines["$wikilink"]="$line"
    all_links_ordered+=("$wikilink")
  done < <(echo "$gh_deduped" | jq -r '
    .[] |
    (.url | capture("github\\.com/(?<org>[^/]+)/(?<repo>[^/]+)/(?<type>issues|pull)/(?<num>[0-9]+)")) as $p |
    "github.com/\($p.org)/\($p.repo)/\($p.type)/\($p.num)\t- [[github.com/\($p.org)/\($p.repo)/\($p.type)/\($p.num)]] \(.title) (**\(.state)**)"
  ')

  for key in "${jira_keys[@]}"; do
    wikilink="${JIRA_ENDPOINT}/${key}"
    local summary="${jira_summary_map[$key]}"
    local status="${jira_status_map[$key]}"
    item_lines["$wikilink"]="- [[${wikilink}]] ${key} ${summary} (**${status}**)"
    all_links_ordered+=("$wikilink")
  done

  # -------------------------------------------------------------------
  # Parse existing file and write output
  # -------------------------------------------------------------------
  local dest_file="${DEST_DIR}/worktodo.md"
  parse_worktodo_sections "$dest_file"
  write_worktodo "$dest_file"

  echo "Wrote ${dest_file}"

  # -------------------------------------------------------------------
  # --sync: create/refresh individual note pages
  # -------------------------------------------------------------------
  if [[ "$sync" == true ]]; then
    echo ""
    echo "Syncing individual note pages ..."

    if [[ "$gh_count" -gt 0 ]]; then
      echo "$gh_deduped" | jq -r '.[].url' | while IFS= read -r url; do
        echo "  -> gh-note.sh $url"
        "$SCRIPT_DIR/gh-note.sh" -d "$DEST_DIR" "$url" || true
      done
    fi

    for key in "${jira_keys[@]}"; do
      echo "  -> jira-note.sh $key"
      "$SCRIPT_DIR/jira-note.sh" -d "$DEST_DIR" "$key" || true
    done
  fi

  echo "Done."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
