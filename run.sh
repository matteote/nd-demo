#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Launch the Spanner Graph Agent in web, dev (ADK), or CLI mode.
# Usage:
#   ./run.sh          # Launch custom FastAPI web UI on $PORT (default 8080)
#   ./run.sh web      # Same as above
#   ./run.sh dev      # Launch built-in ADK developer UI (adk web)
#   ./run.sh cli      # Launch interactive terminal chat (adk run)

set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$AGENT_DIR"

MODE="${1:-web}"
PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"

# Load .env if present
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

# Ensure Spanner client workarounds are active before Python starts
export GOOGLE_CLOUD_SPANNER_MULTIPLEXED_SESSIONS="${GOOGLE_CLOUD_SPANNER_MULTIPLEXED_SESSIONS:-false}"
export SPANNER_DISABLE_BUILTIN_METRICS="${SPANNER_DISABLE_BUILTIN_METRICS:-true}"

print_banner() {
  local mode_label="$1"
  echo "============================================================"
  echo " Spanner Graph Agent (${mode_label})"
  echo "------------------------------------------------------------"
  echo " Local URL:   http://localhost:${PORT}"
  if [[ -n "${WEB_HOST:-}" ]]; then
    echo " Cloud Shell: https://${PORT}-${WEB_HOST}"
  else
    echo " Cloud Shell: Click 'Web Preview' -> 'Preview on port ${PORT}'"
  fi
  echo "============================================================"
}

case "$MODE" in
  web)
    print_banner "Web Interface"
    exec uv run --frozen uvicorn web.server:app --host "$HOST" --port "$PORT"
    ;;
  dev)
    print_banner "ADK Developer UI"
    exec uv run --frozen adk web \
      --host "$HOST" \
      --port "$PORT" \
      --allow_origins "regex:https://.*\.cloudshell\.dev,http://localhost:.*" \
      graph_agent
    ;;
  cli)
    echo "============================================================"
    echo " Spanner Graph Agent (Interactive CLI)"
    echo "============================================================"
    exec uv run --frozen adk run graph_agent
    ;;
  *)
    echo "Usage: ./run.sh [web|dev|cli]" >&2
    exit 1
    ;;
esac
