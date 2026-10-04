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

"""Spanner Property Graph schema introspection tool for fallback Gemini NL2GQL."""

import json
import logging
from typing import Any

from google.cloud import spanner

from . import config

logger = logging.getLogger(__name__)


def get_graph_schema(
    project_id: str | None = None,
    instance_id: str | None = None,
    database_id: str | None = None,
    graph_ids: list[str] | None = None,
) -> dict[str, Any]:
  """Fetches Spanner Property Graph metadata and DDL semantic annotations.

  Queries `INFORMATION_SCHEMA.PROPERTY_GRAPHS` for the target graphs and
  supplements with a local `schema.sql` DDL file when present.

  Args:
      project_id: GCP project ID containing the Spanner instance.
      instance_id: Cloud Spanner instance ID.
      database_id: Cloud Spanner database ID.
      graph_ids: Optional list of property graph names to filter.

  Returns:
      Dictionary containing status, graphs metadata from INFORMATION_SCHEMA,
      and optional CREATE PROPERTY GRAPH DDL text if `schema.sql` is present.
  """
  settings = config.get_settings(project_id)
  resolved_project = project_id or settings.spanner_project_id
  resolved_instance = instance_id or settings.spanner_instance_id
  resolved_database = database_id or settings.spanner_database_id
  resolved_graphs = graph_ids or settings.graph_ids_list

  ddl_snippet = ""
  schema_file = config.REPO_ROOT / "schema.sql"
  if schema_file.is_file():
    raw_sql = schema_file.read_text(encoding="utf-8")
    idx = raw_sql.upper().find("CREATE PROPERTY GRAPH")
    ddl_snippet = raw_sql[idx:].strip() if idx != -1 else raw_sql.strip()

  if not resolved_project:
    result_err: dict[str, Any] = {
        "status": "error",
        "message": (
            "GCP project ID is not configured. Run ./setup.sh or set "
            "GOOGLE_CLOUD_PROJECT."
        ),
    }
    if ddl_snippet:
      result_err["property_graph_ddl"] = ddl_snippet
    return result_err

  try:
    client = spanner.Client(project=resolved_project)
    instance = client.instance(resolved_instance)
    database = instance.database(resolved_database)

    sql = (
        "SELECT PROPERTY_GRAPH_NAME, "
        "TO_JSON_STRING(PROPERTY_GRAPH_METADATA_JSON) AS metadata_json "
        "FROM INFORMATION_SCHEMA.PROPERTY_GRAPHS"
    )
    graphs: list[dict[str, Any]] = []
    with database.snapshot() as snapshot:
      for row in snapshot.execute_sql(sql):
        graph_name = row[0]
        if resolved_graphs and graph_name not in resolved_graphs:
          continue
        try:
          metadata = json.loads(row[1]) if row[1] else {}
        except (TypeError, ValueError):
          metadata = {"raw": row[1]}
        graphs.append({
            "graph_name": graph_name,
            "metadata": metadata,
        })

    graph_label = resolved_graphs[0] if resolved_graphs else "GraphName"
    result_ok: dict[str, Any] = {
        "status": "success",
        "project_id": resolved_project,
        "instance_id": resolved_instance,
        "database_id": resolved_database,
        "graphs": graphs,
        "gql_syntax_notes": [
            f"Wrap GQL queries in SELECT * FROM GRAPH_TABLE({graph_label} MATCH ... COLUMNS (...)) or start directly with GRAPH {graph_label} MATCH ... RETURN ...",
            "ISO GQL reserves path-mode keywords WALK, TRAIL, SIMPLE, and ACYCLIC. Never use reserved keywords as unquoted node or edge variable names; choose a different variable alias or backtick-escape the identifier.",
            "Ground all node labels, edge labels, property names, and edge directions strictly in the metadata returned from INFORMATION_SCHEMA.PROPERTY_GRAPHS.",
        ],
    }
    if ddl_snippet:
      result_ok["property_graph_ddl"] = ddl_snippet
    return result_ok
  except Exception as exc:
    logger.exception("Error querying INFORMATION_SCHEMA.PROPERTY_GRAPHS")
    result_exc: dict[str, Any] = {
        "status": "error",
        "project_id": resolved_project,
        "instance_id": resolved_instance,
        "database_id": resolved_database,
        "message": str(exc),
    }
    if ddl_snippet:
      result_exc["property_graph_ddl"] = ddl_snippet
    return result_exc
