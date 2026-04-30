#!/usr/bin/env bash
# Stdio MCP bridge for Vikunja via @ivotoby/openapi-mcp-server.
# Set VIKUNJA_TOKEN in Cursor MCP env (or export before launch).
set -euo pipefail
if [[ -z "${VIKUNJA_TOKEN:-}" ]]; then
  echo "vikunja-openapi-mcp.sh: set VIKUNJA_TOKEN (Vikunja API token)" >&2
  exit 1
fi
# OpenAPI operations use paths like /projects; base must be …/api/v1 (not the SPA origin).
_origin="${VIKUNJA_API_BASE_URL:-http://127.0.0.1:3456}"
_origin="${_origin%/}"
case "$_origin" in
  */api/v1) export API_BASE_URL="$_origin" ;;
  *) export API_BASE_URL="${_origin}/api/v1" ;;
esac
export OPENAPI_SPEC_PATH="${VIKUNJA_OPENAPI_SPEC:-${API_BASE_URL}/docs.json}"
export API_HEADERS="Authorization:Bearer ${VIKUNJA_TOKEN}"
exec npx -y @ivotoby/openapi-mcp-server "$@"
