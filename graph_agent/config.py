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

"""Centralized configuration for the Spanner Graph NL2GQL Agent."""

from dataclasses import dataclass
import os
import pathlib
from dotenv import load_dotenv
import google.auth
from google.auth import exceptions as auth_exceptions

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

if ENV_PATH.is_file():
  load_dotenv(ENV_PATH, override=False)

# Workarounds for google-cloud-spanner 3.71.0 + google-adk 2.10.0:
# 1. DatabaseSessionsManager._maintain_multiplexed_session uses a blocking
#    10-minute sleep instead of Event.wait(600), which causes database.close()
#    in google.adk.tools.spanner.query_tool.execute_sql to hang on teardown.
# 2. Built-in OpenTelemetry metrics emit incomplete attributes warnings.
os.environ.setdefault("GOOGLE_CLOUD_SPANNER_MULTIPLEXED_SESSIONS", "false")
os.environ.setdefault("SPANNER_DISABLE_BUILTIN_METRICS", "true")
os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")


def parse_bool_env(var_name: str, default: bool = False) -> bool:
  """Parses a boolean environment variable."""
  val = os.getenv(var_name)
  if val is None:
    return default
  return val.strip().lower() in ("1", "true", "yes", "on")


def resolve_project_id(explicit: str | None = None) -> str:
  """Resolves the GCP project ID from explicit value, environment, or ADC."""
  if explicit and explicit.strip():
    return explicit.strip()

  for env_key in (
      "SPANNER_PROJECT_ID",
      "GOOGLE_CLOUD_PROJECT",
      "DEVSHELL_PROJECT_ID",
      "GCLOUD_PROJECT",
  ):
    val = os.getenv(env_key)
    if val and val.strip():
      return val.strip()

  try:
    _, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if adc_project and adc_project.strip():
      return adc_project.strip()
  except (auth_exceptions.DefaultCredentialsError, OSError):
    pass

  return ""


@dataclass(frozen=True)
class Settings:
  """Runtime settings resolved from environment variables and defaults."""

  project_id: str
  spanner_project_id: str
  google_cloud_location: str
  spanner_location: str
  spanner_instance_id: str
  spanner_database_id: str
  spanner_graph_ids: tuple[str, ...]
  query_data_api_version: str
  query_data_location: str
  query_data_execute_query: bool
  query_data_include_raw: bool
  gemini_model: str
  nl2gql_backend: str
  show_sample_prompts: bool = True

  @property
  def graph_ids_list(self) -> list[str]:
    return list(self.spanner_graph_ids)


def get_settings(project_id: str | None = None) -> Settings:
  """Builds a Settings snapshot from current environment variables."""
  resolved_project = resolve_project_id(project_id)
  spanner_project = (
      os.getenv("SPANNER_PROJECT_ID", "").strip() or resolved_project
  )
  raw_graphs = os.getenv("SPANNER_GRAPH_IDS", "TransportGraph")
  graph_ids = tuple(g.strip() for g in raw_graphs.split(",") if g.strip()) or (
      "TransportGraph",
  )
  backend = os.getenv("NL2GQL_BACKEND", "querydata").strip().lower()
  if backend not in ("querydata", "gemini"):
    backend = "querydata"

  return Settings(
      project_id=resolved_project,
      spanner_project_id=spanner_project,
      google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip()
      or "global",
      spanner_location=os.getenv("SPANNER_LOCATION", "europe-west1").strip()
      or "europe-west1",
      spanner_instance_id=os.getenv(
          "SPANNER_INSTANCE_ID", "transport-graph-instance"
      ).strip()
      or "transport-graph-instance",
      spanner_database_id=os.getenv(
          "SPANNER_DATABASE_ID", "transport-graph"
      ).strip()
      or "transport-graph",
      spanner_graph_ids=graph_ids,
      query_data_api_version=os.getenv(
          "QUERY_DATA_API_VERSION", "v1alpha"
      ).strip()
      or "v1alpha",
      query_data_location=os.getenv(
          "QUERY_DATA_LOCATION", "us-central1"
      ).strip()
      or "us-central1",
      query_data_execute_query=parse_bool_env(
          "QUERY_DATA_EXECUTE_QUERY", default=True
      ),
      query_data_include_raw=parse_bool_env(
          "QUERY_DATA_INCLUDE_RAW", default=False
      ),
      gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
      or "gemini-3.8-flash",
      nl2gql_backend=backend,
      show_sample_prompts=parse_bool_env(
          "SHOW_SAMPLE_PROMPTS", default=True
      ),
  )
