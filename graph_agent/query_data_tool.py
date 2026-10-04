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

"""QueryData REST API Tool for NL2GQL Spanner Graph queries."""

import logging
from typing import Any

import google.auth
import google.auth.transport.requests
import requests

from . import config

logger = logging.getLogger(__name__)


def get_default_generate_query_result() -> bool:
  """Returns whether QueryData should execute the generated query by default."""
  return config.parse_bool_env("QUERY_DATA_EXECUTE_QUERY", default=True)


_INITIAL_SETTINGS = config.get_settings()
DEFAULT_API_VERSION = _INITIAL_SETTINGS.query_data_api_version
DEFAULT_QUERY_DATA_LOCATION = _INITIAL_SETTINGS.query_data_location
DEFAULT_PROJECT_ID = _INITIAL_SETTINGS.spanner_project_id
DEFAULT_SPANNER_LOCATION = _INITIAL_SETTINGS.spanner_location
DEFAULT_INSTANCE_ID = _INITIAL_SETTINGS.spanner_instance_id
DEFAULT_DATABASE_ID = _INITIAL_SETTINGS.spanner_database_id
DEFAULT_GRAPH_IDS = _INITIAL_SETTINGS.graph_ids_list
DEFAULT_GENERATE_QUERY_RESULT = _INITIAL_SETTINGS.query_data_execute_query


def _get_bearer_token() -> str:
  """Obtains OAuth2 bearer access token using Application Default Credentials (ADC)."""
  credentials, _ = google.auth.default(
      scopes=["https://www.googleapis.com/auth/cloud-platform"]
  )
  auth_req = google.auth.transport.requests.Request()
  credentials.refresh(auth_req)
  return credentials.token


def query_data(
    prompt: str,
    api_version: str | None = None,
    project_id: str | None = None,
    query_data_location: str | None = None,
    spanner_location: str | None = None,
    instance_id: str | None = None,
    database_id: str | None = None,
    graph_ids: list[str] | None = None,
    context_set_id: str | None = None,
    generate_query_result: bool | None = None,
    generate_natural_language_answer: bool | None = None,
    include_raw: bool | None = None,
    timeout_sec: int = 60,
) -> dict[str, Any]:
  """Queries graph data using natural language via direct HTTP REST POST to QueryData endpoint.

  Targets:
  https://geminidataanalytics.googleapis.com/{api_version}/projects/{project_id}/locations/{query_data_location}:queryData

  Args:
      prompt: Natural language user question about the graph database.
      api_version: API version string (default "v1alpha").
      project_id: GCP project ID containing the Spanner database.
      query_data_location: Location/region of the QueryData endpoint (e.g. "us-central1" or "global").
      spanner_location: Region of the Spanner instance (e.g. "europe-west1").
      instance_id: Spanner instance ID.
      database_id: Spanner database ID.
      graph_ids: List of Spanner property graph IDs to query.
      context_set_id: Optional context set ID for schema / template grounding.
      generate_query_result: Whether QueryData should also execute the generated query on Spanner.
          Defaults to the `QUERY_DATA_EXECUTE_QUERY` environment variable (`True` if unset).
      generate_natural_language_answer: Whether QueryData should synthesize a natural language
          answer from executed query results. Defaults to `generate_query_result`.
      include_raw: Whether to attach the full raw API JSON response. Defaults to
          `QUERY_DATA_INCLUDE_RAW` (`False` if unset).
      timeout_sec: Request timeout duration in seconds.

  Returns:
      A dictionary containing the generated GQL query, intent explanation,
      query execution results, natural language answer, and response metadata.
  """
  settings = config.get_settings(project_id)
  resolved_api_version = api_version or settings.query_data_api_version
  resolved_project_id = project_id or settings.spanner_project_id
  resolved_qd_location = query_data_location or settings.query_data_location
  resolved_spanner_location = spanner_location or settings.spanner_location
  resolved_instance_id = instance_id or settings.spanner_instance_id
  resolved_database_id = database_id or settings.spanner_database_id
  resolved_graph_ids = (
      graph_ids if graph_ids is not None else settings.graph_ids_list
  )
  if generate_query_result is None:
    generate_query_result = get_default_generate_query_result()
  if generate_natural_language_answer is None:
    generate_natural_language_answer = generate_query_result
  if include_raw is None:
    include_raw = settings.query_data_include_raw

  if not resolved_project_id:
    return {
        "status": "error",
        "message": (
            "GCP project ID is not configured. Run ./setup.sh or set "
            "GOOGLE_CLOUD_PROJECT."
        ),
        "prompt": prompt,
    }

  parent = f"projects/{resolved_project_id}/locations/{resolved_qd_location}"
  url = f"https://geminidataanalytics.googleapis.com/{resolved_api_version}/{parent}:queryData"

  spanner_ref: dict[str, Any] = {
      "databaseReference": {
          "engine": "GOOGLE_SQL",
          "projectId": resolved_project_id,
          "region": resolved_spanner_location,
          "instanceId": resolved_instance_id,
          "databaseId": resolved_database_id,
          "graphIds": resolved_graph_ids,
      }
  }

  if context_set_id:
    spanner_ref["agentContextReference"] = {"contextSetId": context_set_id}

  payload: dict[str, Any] = {
      "parent": parent,
      "prompt": prompt,
      "context": {
          "datasourceReferences": {
              "spannerReference": spanner_ref,
          }
      },
      "generationOptions": {
          "generateQueryResult": generate_query_result,
          "generateNaturalLanguageAnswer": generate_natural_language_answer,
          "generateExplanation": True,
          "generateDisambiguationQuestion": True,
      },
      "surface": "CONVERSATIONAL_ANALYTICS",
  }

  try:
    token = _get_bearer_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": resolved_project_id,
    }

    logger.info(
        "Posting QueryData REST request to %s (generateQueryResult=%s)",
        url,
        generate_query_result,
    )
    response = requests.post(
        url, headers=headers, json=payload, timeout=timeout_sec
    )
    if not response.ok:
      try:
        err_body = response.json()
      except Exception:
        err_body = response.text
      return {
          "status": "error",
          "http_status": response.status_code,
          "api_version": resolved_api_version,
          "endpoint_url": url,
          "query_executed_by_query_data": generate_query_result,
          "message": (
              f"HTTP {response.status_code} from QueryData endpoint. "
              "Run `uv run python scripts/doctor.py` to check IAM roles and "
              "Spanner Graph QueryData allowlisting."
          ),
          "error_details": err_body,
          "prompt": prompt,
      }

    res_json = response.json()
    result: dict[str, Any] = {
        "status": "success",
        "api_version": resolved_api_version,
        "endpoint_url": url,
        "query_executed_by_query_data": generate_query_result,
        "generated_query": res_json.get("generatedQuery", ""),
        "intent_explanation": res_json.get("intentExplanation", ""),
        "natural_language_answer": res_json.get("naturalLanguageAnswer", ""),
        "disambiguation_questions": res_json.get(
            "disambiguationQuestion", []
        ),
        "query_result": res_json.get("queryResult", {}),
    }
    if include_raw:
      result["raw_response"] = res_json
    return result
  except Exception as e:
    logger.exception("Error executing direct REST QueryData POST to %s", url)
    return {
        "status": "error",
        "api_version": resolved_api_version,
        "endpoint_url": url,
        "message": str(e),
        "prompt": prompt,
    }
