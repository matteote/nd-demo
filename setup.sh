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
# Standalone setup for the Spanner Graph ADK Agent (connects to an
# already-deployed Cloud Spanner database).
#
# Usage:
#   ./setup.sh [PROJECT_ID]
# Optional environment variables:
#   SPANNER_PROJECT_ID=<defaults to PROJECT_ID>
#   SPANNER_LOCATION=europe-west1
#   SPANNER_INSTANCE_ID=transport-graph-instance
#   SPANNER_DATABASE_ID=transport-graph
#   SPANNER_GRAPH_IDS=TransportGraph
#   QUERY_DATA_LOCATION=us-central1
#   QUERY_DATA_EXECUTE_QUERY=false
#   NL2GQL_BACKEND=querydata
#   GEMINI_MODEL=gemini-3.8-flash
#   SKIP_DOCTOR=false

set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$AGENT_DIR"

echo "============================================================"
echo " Spanner Graph Agent - Standalone Agent Setup"
echo "============================================================"

# Load existing .env if present (without modifying it)
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

# 1. Resolve Google Cloud Project ID
PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-${DEVSHELL_PROJECT_ID:-}}}"
if [[ -z "$PROJECT_ID" ]] && command -v gcloud >/dev/null 2>&1; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" || "$PROJECT_ID" == "your-gcp-project-id" ]]; then
  echo "ERROR: Could not determine Google Cloud project ID." >&2
  echo "Run: gcloud config set project YOUR_PROJECT_ID" >&2
  echo "Or pass it directly: ./setup.sh YOUR_PROJECT_ID" >&2
  exit 1
fi
export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
echo "-> Target GCP Project: ${PROJECT_ID}"

# 2. Check required CLI tools (install uv if missing)
if ! command -v gcloud >/dev/null 2>&1; then
  echo "ERROR: Required command 'gcloud' is not installed." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "-> Installing uv package manager..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# 3. Verify Application Default Credentials (ADC)
echo "-> Checking Application Default Credentials (ADC)..."
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo "ADC not found or expired. Launching 'gcloud auth application-default login'..."
  gcloud auth application-default login
fi

gcloud auth application-default set-quota-project "$PROJECT_ID" >/dev/null 2>&1 || true

# 4. Ensure required Vertex AI & Gemini Data Analytics APIs are enabled
echo "-> Ensuring required Agent APIs are enabled..."
gcloud services enable \
  serviceusage.googleapis.com \
  spanner.googleapis.com \
  aiplatform.googleapis.com \
  cloudaicompanion.googleapis.com \
  geminidataanalytics.googleapis.com \
  --project "$PROJECT_ID"

# 5. Sync Python dependencies from lockfile
echo "-> Syncing Python environment with uv..."
if ! uv sync --frozen; then
  uv sync --no-config --default-index https://pypi.org/simple
fi

# 6. Write .env pointing to the existing Cloud Spanner database (only if .env does not already exist)
if [[ -f ".env" ]]; then
  echo "-> Existing ${AGENT_DIR}/.env found; leaving it untouched."
else
  echo "-> Writing agent .env configuration..."
  cat > .env <<EOF
GOOGLE_GENAI_USE_ENTERPRISE=TRUE
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-global}

SPANNER_PROJECT_ID=${SPANNER_PROJECT_ID:-${PROJECT_ID}}
SPANNER_LOCATION=${SPANNER_LOCATION:-europe-west1}
SPANNER_INSTANCE_ID=${SPANNER_INSTANCE_ID:-transport-graph-instance}
SPANNER_DATABASE_ID=${SPANNER_DATABASE_ID:-transport-graph}
SPANNER_GRAPH_IDS=${SPANNER_GRAPH_IDS:-TransportGraph}

QUERY_DATA_API_VERSION=${QUERY_DATA_API_VERSION:-v1alpha}
QUERY_DATA_LOCATION=${QUERY_DATA_LOCATION:-us-central1}
QUERY_DATA_EXECUTE_QUERY=${QUERY_DATA_EXECUTE_QUERY:-true}
QUERY_DATA_INCLUDE_RAW=${QUERY_DATA_INCLUDE_RAW:-false}
NL2GQL_BACKEND=${NL2GQL_BACKEND:-querydata}
GEMINI_MODEL=${GEMINI_MODEL:-gemini-3.8-flash}
SHOW_SAMPLE_PROMPTS=${SHOW_SAMPLE_PROMPTS:-true}

GOOGLE_CLOUD_SPANNER_MULTIPLEXED_SESSIONS=false
SPANNER_DISABLE_BUILTIN_METRICS=true
EOF
  echo "-> Wrote configuration to ${AGENT_DIR}/.env"
fi

# 7. Run preflight doctor verification against existing Spanner database
if [[ "${SKIP_DOCTOR:-false}" != "true" ]]; then
  echo "-> Running preflight verification (scripts/doctor.py)..."
  .venv/bin/python scripts/doctor.py
fi

echo ""
echo "============================================================"
echo " Agent Setup Complete!"
echo " Start the web interface with: ./run.sh"
echo " Or deploy to Cloud Run with:  ./deploy.sh"
echo "============================================================"
