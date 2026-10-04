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
# Tear down the Cloud Run agent service without modifying the Cloud Spanner database.
# Usage:
#   ./teardown.sh [PROJECT_ID]

set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$AGENT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-${SPANNER_PROJECT_ID:-}}}"
if [[ -z "$PROJECT_ID" ]] && command -v gcloud >/dev/null 2>&1; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" || "$PROJECT_ID" == "your-gcp-project-id" ]]; then
  echo "ERROR: Could not determine Google Cloud project ID." >&2
  echo "Usage: ./teardown.sh YOUR_PROJECT_ID" >&2
  exit 1
fi

REGION="${REGION:-${SPANNER_LOCATION:-europe-west1}}"
SERVICE_NAME="${SERVICE_NAME:-spanner-graph-agent}"

echo "============================================================"
echo " Tearing down Cloud Run Agent Service (${SERVICE_NAME})"
echo " (Cloud Spanner database is preserved)"
echo "============================================================"

if gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" >/dev/null 2>&1; then
  echo "-> Deleting Cloud Run service '${SERVICE_NAME}' in ${REGION}..."
  gcloud run services delete "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --quiet
  echo "-> Deleted Cloud Run service '${SERVICE_NAME}'."
else
  echo "-> Cloud Run service '${SERVICE_NAME}' not found in ${REGION}; nothing to delete."
fi
