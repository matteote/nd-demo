#!/usr/bin/env python3
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

"""Preflight diagnostics for the Spanner Graph NL2GQL Agent."""

import argparse
from dataclasses import asdict, dataclass
import json
import os
import pathlib
import sys
import time
from typing import Any

# Ensure repo root is importable when invoked as `python scripts/doctor.py`
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("GOOGLE_CLOUD_SPANNER_MULTIPLEXED_SESSIONS", "false")
os.environ.setdefault("SPANNER_DISABLE_BUILTIN_METRICS", "true")

import google.auth
import google.auth.transport.requests
from google.cloud import spanner
from google import genai
import requests

from graph_agent import config
from graph_agent import query_data_tool

REQUIRED_APIS = (
    "spanner.googleapis.com",
    "aiplatform.googleapis.com",
    "geminidataanalytics.googleapis.com",
    "cloudaicompanion.googleapis.com",
)


@dataclass
class CheckResult:
  name: str
  status: str  # "ok", "warn", "fail"
  summary: str
  remediation: str = ""
  details: dict[str, Any] | None = None


def check_credentials_and_project(
    settings: config.Settings,
) -> tuple[CheckResult, str | None]:
  """Checks Application Default Credentials and GCP project configuration."""
  if not settings.project_id:
    return (
        CheckResult(
            name="GCP Project & Credentials",
            status="fail",
            summary="No GCP project ID configured.",
            remediation=(
                "Run `./setup.sh <YOUR_PROJECT_ID>` or export "
                "`GOOGLE_CLOUD_PROJECT=<YOUR_PROJECT_ID>`."
            ),
        ),
        None,
    )

  try:
    creds, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    principal = getattr(creds, "service_account_email", None) or "user-adc"
    return (
        CheckResult(
            name="GCP Project & Credentials",
            status="ok",
            summary=(
                f"Project `{settings.project_id}` authenticated via ADC "
                f"({principal})."
            ),
            details={
                "project_id": settings.project_id,
                "adc_project": adc_project,
                "principal": principal,
            },
        ),
        creds.token,
    )
  except Exception as exc:
    return (
        CheckResult(
            name="GCP Project & Credentials",
            status="fail",
            summary=f"Failed to obtain Application Default Credentials: {exc}",
            remediation=(
                "Run `gcloud auth application-default login` (or open Cloud "
                "Shell where credentials are automatic)."
            ),
        ),
        None,
    )


def check_enabled_apis(
    settings: config.Settings, token: str
) -> CheckResult:
  """Verifies required Google Cloud APIs are enabled on the target project."""
  url = (
      f"https://serviceusage.googleapis.com/v1/projects/{settings.project_id}"
      "/services?filter=state:ENABLED&pageSize=200"
  )
  headers = {
      "Authorization": f"Bearer {token}",
      "X-Goog-User-Project": settings.project_id,
  }
  try:
    resp = requests.get(url, headers=headers, timeout=20)
    if not resp.ok:
      return CheckResult(
          name="Required GCP APIs",
          status="warn",
          summary=(
              f"Could not list enabled APIs via Service Usage "
              f"(HTTP {resp.status_code}). Continuing with direct checks."
          ),
          remediation=(
              "Ensure `serviceusage.googleapis.com` is enabled and your "
              "account has `roles/serviceusage.serviceUsageConsumer`."
          ),
      )
    data = resp.json()
    enabled = {
        svc.get("config", {}).get("name", "")
        for svc in data.get("services", [])
    }
    missing = [api for api in REQUIRED_APIS if api not in enabled]
    if missing:
      apis_str = " ".join(missing)
      return CheckResult(
          name="Required GCP APIs",
          status="fail",
          summary=f"Missing enabled APIs: {', '.join(missing)}",
          remediation=(
              f"Run: `gcloud services enable {apis_str} "
              f"--project={settings.project_id}` or `./setup.sh`."
          ),
          details={"missing_apis": missing},
      )
    return CheckResult(
        name="Required GCP APIs",
        status="ok",
        summary=f"All {len(REQUIRED_APIS)} required APIs are enabled.",
        details={"enabled_apis": list(REQUIRED_APIS)},
    )
  except Exception as exc:
    return CheckResult(
        name="Required GCP APIs",
        status="warn",
        summary=f"Could not query Service Usage API: {exc}",
    )


def check_spanner_graph(settings: config.Settings) -> CheckResult:
  """Verifies Cloud Spanner instance, database, TransportGraph DDL, and seed data."""
  target = (
      f"projects/{settings.spanner_project_id}/instances/"
      f"{settings.spanner_instance_id}/databases/{settings.spanner_database_id}"
  )
  try:
    client = spanner.Client(project=settings.spanner_project_id)
    instance = client.instance(settings.spanner_instance_id)
    database = instance.database(settings.spanner_database_id)

    graph_rows: dict[str, dict[str, Any]] = {}
    with database.snapshot() as snapshot:
      for row in snapshot.execute_sql(
          "SELECT PROPERTY_GRAPH_NAME, "
          "TO_JSON_STRING(PROPERTY_GRAPH_METADATA_JSON) "
          "FROM INFORMATION_SCHEMA.PROPERTY_GRAPHS"
      ):
        try:
          meta = json.loads(row[1]) if row[1] else {}
        except (TypeError, ValueError):
          meta = {}
        graph_rows[row[0]] = meta

    graphs = list(graph_rows.keys())
    missing_graphs = [
        g for g in settings.spanner_graph_ids if g not in graphs
    ]
    if missing_graphs:
      return CheckResult(
          name="Cloud Spanner Property Graph",
          status="fail",
          summary=(
              f"Property graph(s) {missing_graphs} not found in {target} "
              f"(found: {graphs})."
          ),
          remediation=(
              "Ensure the target Spanner database has the configured "
              "property graph (`SPANNER_GRAPH_IDS`) provisioned."
          ),
      )

    primary_graph = settings.spanner_graph_ids[0]
    primary_meta = graph_rows.get(primary_graph, {})
    node_tables = primary_meta.get("nodeTables") or []
    edge_tables = primary_meta.get("edgeTables") or []

    return CheckResult(
        name="Cloud Spanner Property Graph",
        status="ok",
        summary=(
            f"Connected to `{target}`; graph `{primary_graph}` "
            f"verified ({len(node_tables)} node tables, "
            f"{len(edge_tables)} edge tables)."
        ),
        details={
            "graphs": graphs,
            "node_table_count": len(node_tables),
            "edge_table_count": len(edge_tables),
        },
    )
  except Exception as exc:
    return CheckResult(
        name="Cloud Spanner Property Graph",
        status="fail",
        summary=f"Failed to query Cloud Spanner ({target}): {exc}",
        remediation=(
            "Verify `SPANNER_PROJECT_ID`, `SPANNER_INSTANCE_ID`, and `SPANNER_DATABASE_ID` "
            "in `.env` point to your deployed Spanner database and your principal has "
            "`roles/spanner.databaseReader`."
        ),
    )


def check_gemini_model(settings: config.Settings) -> CheckResult:
  """Verifies Vertex AI Gemini model connectivity."""
  t0 = time.monotonic()
  try:
    client = genai.Client(
        vertexai=True,
        project=settings.project_id,
        location=settings.google_cloud_location,
    )
    resp = client.models.generate_content(
        model=settings.gemini_model,
        contents="Reply with the single word OK.",
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    text = (resp.text or "").strip()
    return CheckResult(
        name="Vertex AI Gemini Model",
        status="ok",
        summary=(
            f"Model `{settings.gemini_model}` ({settings.google_cloud_location}) "
            f"responded in {elapsed_ms} ms."
        ),
        details={"model": settings.gemini_model, "response": text},
    )
  except Exception as exc:
    return CheckResult(
        name="Vertex AI Gemini Model",
        status="fail",
        summary=(
            f"Vertex AI call to `{settings.gemini_model}` in "
            f"`{settings.google_cloud_location}` failed: {exc}"
        ),
        remediation=(
            "Verify `aiplatform.googleapis.com` is enabled, your principal has "
            "`roles/aiplatform.user`, or set `GEMINI_MODEL` in `.env`."
        ),
    )


def check_query_data(settings: config.Settings) -> CheckResult:
  """Verifies Gemini Data Analytics QueryData NL2GQL translation for the configured graph."""
  res = query_data_tool.query_data(
      prompt="Show 5 nodes in the graph",
      project_id=settings.spanner_project_id,
      generate_query_result=False,
  )
  if res.get("status") == "success" and res.get("generated_query"):
    query_preview = " ".join(res["generated_query"].split())
    return CheckResult(
        name="Gemini Data Analytics QueryData (NL2GQL)",
        status="ok",
        summary=f"QueryData generated GQL: `{query_preview[:90]}`",
        details={"generated_query": res["generated_query"]},
    )

  http_status = res.get("http_status")
  err_details = json.dumps(res.get("error_details", res.get("message", "")))

  if http_status == 403:
    return CheckResult(
        name="Gemini Data Analytics QueryData (NL2GQL)",
        status="fail",
        summary=f"HTTP 403 Forbidden from QueryData endpoint: {err_details[:180]}",
        remediation=(
            "Grant `roles/geminidataanalytics.queryDataUser` and "
            "`roles/spanner.databaseReader` to your principal, or set "
            "`NL2GQL_BACKEND=gemini` in `.env` to use direct Gemini GQL generation."
        ),
    )

  status = "warn" if settings.nl2gql_backend == "gemini" else "fail"
  return CheckResult(
      name="Gemini Data Analytics QueryData (NL2GQL)",
      status=status,
      summary=(
          f"QueryData check returned {http_status or 'error'}: "
          f"{err_details[:180]}"
      ),
      remediation=(
          "Spanner Graph support (`graphIds`) in QueryData (`v1alpha`) requires "
          "project allowlisting. If your project is not yet allowlisted, set "
          "`NL2GQL_BACKEND=gemini` in `.env` (the agent also automatically falls "
          "back to `inspect_graph_schema` + `execute_spanner_query`)."
      ),
  )


def run_all_checks(skip_llm: bool = False) -> list[CheckResult]:
  """Runs all preflight checks in sequence."""
  settings = config.get_settings()
  results: list[CheckResult] = []

  cred_check, token = check_credentials_and_project(settings)
  results.append(cred_check)
  if cred_check.status == "fail" or not token:
    return results

  results.append(check_enabled_apis(settings, token))
  results.append(check_spanner_graph(settings))

  if not skip_llm:
    results.append(check_gemini_model(settings))
    results.append(check_query_data(settings))

  return results


def main() -> int:
  parser = argparse.ArgumentParser(
      description="Run preflight checks for the Spanner Graph Agent."
  )
  parser.add_argument(
      "--json", action="store_true", help="Output check results as JSON."
  )
  parser.add_argument(
      "--skip-llm",
      action="store_true",
      help="Skip live Vertex AI Gemini and QueryData RPC checks.",
  )
  args = parser.parse_args()

  results = run_all_checks(skip_llm=args.skip_llm)

  if args.json:
    print(json.dumps([asdict(r) for r in results], indent=2))
  else:
    icons = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}
    print("\n=== Spanner Graph Agent — Preflight Doctor ===")
    for r in results:
      icon = icons.get(r.status, "•")
      print(f"{icon} {r.name}: {r.summary}")
      if r.remediation and r.status != "ok":
        print(f"   ↳ Fix: {r.remediation}")
    print("==============================================\n")

  has_fail = any(r.status == "fail" for r in results)
  if not has_fail and not args.json:
    print("All required checks passed! Run `./run.sh` to start the Web UI.")
  return 1 if has_fail else 0


if __name__ == "__main__":
  sys.exit(main())
