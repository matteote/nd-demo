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
# Standalone Cloud Run deployment for the Spanner Graph Agent.
# Deploys ONLY the agent container and connects it to an already-deployed
# Cloud Spanner database.
#
# Usage:
#   ./deploy.sh                  # Deploy with Identity-Aware Proxy / authenticated access
#   PUBLIC=true ./deploy.sh      # Deploy with unauthenticated access (if org policy permits)
# Optional environment variables:
#   SERVICE_NAME=spanner-graph-agent
#   REGION=<defaults to SPANNER_LOCATION or europe-west1>
#   IAP_MEMBERS="user:you@example.com,domain:example.com"

set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$AGENT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-${SPANNER_PROJECT_ID:-}}"
if [[ -z "$PROJECT_ID" ]] && command -v gcloud >/dev/null 2>&1; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" || "$PROJECT_ID" == "your-gcp-project-id" ]]; then
  echo "ERROR: Could not determine Google Cloud project ID. Run ./setup.sh first." >&2
  exit 1
fi

REGION="${REGION:-${SPANNER_LOCATION:-europe-west1}}"
SERVICE_NAME="${SERVICE_NAME:-spanner-graph-agent}"
SA_NAME="${SA_NAME:-spanner-graph-agent-sa}"
SERVICE_ACCOUNT="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
PUBLIC="${PUBLIC:-false}"

echo "============================================================"
echo " Deploying ${SERVICE_NAME} to Cloud Run (${PROJECT_ID} / ${REGION})"
echo "============================================================"

# 1. Enable Cloud Run, Cloud Build, Artifact Registry, IAM, and IAP APIs
echo "-> Ensuring Cloud Run, Build & Agent APIs are enabled..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iap.googleapis.com \
  spanner.googleapis.com \
  aiplatform.googleapis.com \
  cloudaicompanion.googleapis.com \
  geminidataanalytics.googleapis.com \
  --project "$PROJECT_ID"

# 2. Ensure least-privilege runtime Service Account exists and has required roles
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "-> Creating service account ${SERVICE_ACCOUNT}..."
  gcloud iam service-accounts create "$SA_NAME" \
    --project "$PROJECT_ID" \
    --display-name "Spanner Graph ADK Agent Service Account"
fi

SA_ROLES=(
  "roles/spanner.databaseReader"
  "roles/aiplatform.user"
  "roles/cloudaicompanion.user"
  "roles/geminidataanalytics.queryDataUser"
  "roles/geminidataanalytics.dataAgentStatelessUser"
  "roles/serviceusage.serviceUsageConsumer"
)
echo "-> Ensuring IAM roles on ${SERVICE_ACCOUNT}..."
for role in "${SA_ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="$role" \
    --condition=None >/dev/null 2>&1 || true
done

# 3. Generate .env.cloudrun.yaml from current environment / .env
ENV_YAML=".env.cloudrun.yaml"
cat > "$ENV_YAML" <<EOF
GOOGLE_GENAI_USE_ENTERPRISE: "TRUE"
GOOGLE_CLOUD_PROJECT: "${PROJECT_ID}"
GOOGLE_CLOUD_LOCATION: "${GOOGLE_CLOUD_LOCATION:-global}"
GEMINI_MODEL: "${GEMINI_MODEL:-gemini-3.8-flash}"
SPANNER_PROJECT_ID: "${SPANNER_PROJECT_ID:-${PROJECT_ID}}"
SPANNER_LOCATION: "${SPANNER_LOCATION:-${REGION}}"
SPANNER_INSTANCE_ID: "${SPANNER_INSTANCE_ID:-transport-graph-instance}"
SPANNER_DATABASE_ID: "${SPANNER_DATABASE_ID:-transport-graph}"
SPANNER_GRAPH_IDS: "${SPANNER_GRAPH_IDS:-TransportGraph}"
QUERY_DATA_API_VERSION: "${QUERY_DATA_API_VERSION:-v1alpha}"
QUERY_DATA_LOCATION: "${QUERY_DATA_LOCATION:-us-central1}"
QUERY_DATA_EXECUTE_QUERY: "${QUERY_DATA_EXECUTE_QUERY:-true}"
NL2GQL_BACKEND: "${NL2GQL_BACKEND:-querydata}"
SHOW_SAMPLE_PROMPTS: "${SHOW_SAMPLE_PROMPTS:-true}"
GOOGLE_CLOUD_SPANNER_MULTIPLEXED_SESSIONS: "false"
SPANNER_DISABLE_BUILTIN_METRICS: "true"
EOF

trap 'rm -f "$ENV_YAML"' EXIT

# 4. Build & deploy from ./agent directory
DEPLOY_ARGS=(
  "run" "deploy" "$SERVICE_NAME"
  "--source" "."
  "--project" "$PROJECT_ID"
  "--region" "$REGION"
  "--service-account" "$SERVICE_ACCOUNT"
  "--env-vars-file" "$ENV_YAML"
  "--port" "8080"
  "--memory" "1Gi"
  "--cpu" "1"
  "--timeout" "300"
)

if [[ "$PUBLIC" == "true" ]]; then
  echo "-> Deploying with --allow-unauthenticated (PUBLIC=true)..."
  DEPLOY_ARGS+=("--allow-unauthenticated")
else
  echo "-> Deploying with --no-allow-unauthenticated (IAP / authenticated access)..."
  DEPLOY_ARGS+=("--no-allow-unauthenticated")
fi

if [[ "$PUBLIC" != "true" ]] && gcloud beta run deploy --help 2>/dev/null | grep -q -- "--iap"; then
  echo "-> Enabling Cloud Run direct IAP integration (--iap)..."
  gcloud beta "${DEPLOY_ARGS[@]}" --iap
else
  gcloud "${DEPLOY_ARGS[@]}"
fi

# 5. Grant Invoker access to caller (and optional IAP_MEMBERS)
CALLER_EMAIL="$(gcloud config get-value account 2>/dev/null || true)"
MEMBERS=()
if [[ -n "$CALLER_EMAIL" && "$CALLER_EMAIL" != "(unset)" ]]; then
  MEMBERS+=("user:${CALLER_EMAIL}")
fi
if [[ -n "${IAP_MEMBERS:-}" ]]; then
  IFS=',' read -ra EXTRA_MEMBERS <<< "$IAP_MEMBERS"
  for m in "${EXTRA_MEMBERS[@]}"; do
    MEMBERS+=("$m")
  done
fi

for member in "${MEMBERS[@]}"; do
  echo "-> Granting Cloud Run Invoker to ${member}..."
  gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --member "$member" \
    --role "roles/run.invoker" >/dev/null 2>&1 || true
done

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format="value(status.url)")"

echo ""
echo "============================================================"
echo " Agent Deployment Complete!"
echo " Service URL: ${SERVICE_URL}"
if [[ "$PUBLIC" != "true" ]]; then
  echo " Access Mode: Authenticated / IAP"
  echo " Tip: To access via local authenticated proxy in Cloud Shell:"
  echo "      gcloud run services proxy ${SERVICE_NAME} --project ${PROJECT_ID} --region ${REGION} --port 8080"
fi
echo "============================================================"
