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

"""Unit and integration tests for the Spanner Graph NL2GQL ADK Agent and Web UI."""

from __future__ import annotations

import json
import os
from unittest import mock

from fastapi.testclient import TestClient
from google.adk.models import base_llm
from google.adk.runners import InMemoryRunner
from google.cloud import spanner
from google.genai import types
import pytest

from graph_agent import agent as nl2gql_agent_module
from graph_agent import config
from graph_agent import graph_schema_tool
from graph_agent import query_data_tool
from scripts import doctor
from web import server as web_server

INTEGRATION_SKIP = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Set RUN_INTEGRATION_TESTS=1 to run live GCP Spanner/ADK integration tests.",
)


def test_config_resolution_and_bool_parsing(monkeypatch):
  """Verifies centralized config resolution and boolean environment parsing."""
  monkeypatch.setenv("TEST_BOOL_VAR", "true")
  assert config.parse_bool_env("TEST_BOOL_VAR") is True
  monkeypatch.setenv("TEST_BOOL_VAR", "1")
  assert config.parse_bool_env("TEST_BOOL_VAR") is True
  monkeypatch.setenv("TEST_BOOL_VAR", "YES")
  assert config.parse_bool_env("TEST_BOOL_VAR") is True
  monkeypatch.setenv("TEST_BOOL_VAR", "false")
  assert config.parse_bool_env("TEST_BOOL_VAR") is False
  monkeypatch.delenv("TEST_BOOL_VAR", raising=False)
  assert config.parse_bool_env("TEST_BOOL_VAR", default=True) is True

  monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "unit-test-project")
  monkeypatch.delenv("SPANNER_PROJECT_ID", raising=False)
  monkeypatch.setenv("SPANNER_INSTANCE_ID", "unit-instance")
  monkeypatch.setenv("SPANNER_DATABASE_ID", "unit-db")
  monkeypatch.setenv("SPANNER_GRAPH_IDS", "GraphA, GraphB")
  monkeypatch.setenv("NL2GQL_BACKEND", "gemini")

  settings = config.get_settings()
  assert settings.project_id == "unit-test-project"
  assert settings.spanner_project_id == "unit-test-project"
  assert settings.spanner_instance_id == "unit-instance"
  assert settings.spanner_database_id == "unit-db"
  assert settings.spanner_graph_ids == ("GraphA", "GraphB")
  assert settings.nl2gql_backend == "gemini"


def test_agent_initialization():
  """Verifies Nl2GqlAgent initializes with expected name, instructions, and tools."""
  mock_model = mock.create_autospec(base_llm.BaseLlm, instance=True)
  agent = nl2gql_agent_module.Nl2GqlAgent(
      model=mock_model,
      name="test_graph_agent",
      api_version="v1alpha",
      project_id="test-gcp-project",
      instance_id="transport-graph-instance",
      database_id="transport-graph",
      graph_ids=["TransportGraph"],
      nl2gql_backend="querydata",
  )

  assert agent.name == "test_graph_agent"
  instruction_str = str(agent.instruction)
  assert "query_graph_data" in instruction_str
  assert "inspect_graph_schema" in instruction_str

  tool_names = [t.name for t in agent.tools if hasattr(t, "name")]
  assert "query_graph_data" in tool_names
  assert "inspect_graph_schema" in tool_names
  assert "execute_spanner_query" in tool_names
  assert (
      agent.generate_query_result
      == query_data_tool.get_default_generate_query_result()
  )


def test_agent_gemini_fallback_backend():
  """Verifies NL2GQL_BACKEND=gemini configures schema-first direct GQL mode."""
  mock_model = mock.create_autospec(base_llm.BaseLlm, instance=True)
  agent = nl2gql_agent_module.Nl2GqlAgent(
      model=mock_model,
      project_id="test-gcp-project",
      nl2gql_backend="gemini",
  )
  assert agent.nl2gql_backend == "gemini"
  instruction_str = str(agent.instruction)
  assert "inspect_graph_schema" in instruction_str
  assert "execute_spanner_query" in instruction_str
  tool_names = [t.name for t in agent.tools if hasattr(t, "name")]
  assert "query_graph_data" not in tool_names
  assert "inspect_graph_schema" in tool_names
  assert "execute_spanner_query" in tool_names


def test_query_data_execute_query_switch_and_session_override(monkeypatch):
  """Verifies QUERY_DATA_EXECUTE_QUERY env var (True by default) and per-session state override."""
  mock_model = mock.create_autospec(base_llm.BaseLlm, instance=True)

  # 1. Default (unset -> true) -> QueryData generates and executes query
  monkeypatch.delenv("QUERY_DATA_EXECUTE_QUERY", raising=False)
  assert query_data_tool.get_default_generate_query_result() is True
  agent_default = nl2gql_agent_module.Nl2GqlAgent(
      model=mock_model, project_id="test-gcp-project"
  )
  assert agent_default.generate_query_result is True

  # 2. Disabled via env var (false) -> query generation only
  monkeypatch.setenv("QUERY_DATA_EXECUTE_QUERY", "false")
  assert query_data_tool.get_default_generate_query_result() is False
  agent_gen_only = nl2gql_agent_module.Nl2GqlAgent(
      model=mock_model, project_id="test-gcp-project"
  )
  assert agent_gen_only.generate_query_result is False

  # 3. Explicitly enabled via env var (true)
  monkeypatch.setenv("QUERY_DATA_EXECUTE_QUERY", "true")
  assert query_data_tool.get_default_generate_query_result() is True
  agent_exec = nl2gql_agent_module.Nl2GqlAgent(
      model=mock_model, project_id="test-gcp-project"
  )
  assert agent_exec.generate_query_result is True

  # 4. Verify REST payload generationOptions sent by query_data() in both modes
  with (
      mock.patch.object(
          query_data_tool, "_get_bearer_token", return_value="fake-token"
      ),
      mock.patch.object(query_data_tool.requests, "post") as mock_post,
  ):
    mock_resp = mock.MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "generatedQuery": "GRAPH TransportGraph MATCH (n) RETURN COUNT(n)"
    }
    mock_post.return_value = mock_resp

    res_false = query_data_tool.query_data(
        "Count all nodes",
        project_id="test-gcp-project",
        generate_query_result=False,
    )
    sent_opts_false = mock_post.call_args.kwargs["json"]["generationOptions"]
    assert sent_opts_false["generateQueryResult"] is False
    assert sent_opts_false["generateNaturalLanguageAnswer"] is False
    assert res_false["query_executed_by_query_data"] is False
    assert "raw_response" not in res_false

    res_true = query_data_tool.query_data(
        "Count all nodes",
        project_id="test-gcp-project",
        generate_query_result=True,
    )
    sent_opts_true = mock_post.call_args.kwargs["json"]["generationOptions"]
    assert sent_opts_true["generateQueryResult"] is True
    assert sent_opts_true["generateNaturalLanguageAnswer"] is True
    assert res_true["query_executed_by_query_data"] is True


def test_graph_schema_tool_metadata_introspection():
  """Verifies get_graph_schema returns INFORMATION_SCHEMA metadata cleanly."""
  with mock.patch.object(graph_schema_tool.spanner, "Client") as mock_client_cls:
    mock_db = (
        mock_client_cls.return_value.instance.return_value.database.return_value
    )
    mock_snapshot = mock_db.snapshot.return_value.__enter__.return_value
    mock_snapshot.execute_sql.return_value = [
        ("TransportGraph", json.dumps({"nodeTables": [{"name": "Nodes"}]}))
    ]

    result = graph_schema_tool.get_graph_schema(
        project_id="test-gcp-project",
        instance_id="transport-graph-instance",
        database_id="transport-graph",
        graph_ids=["TransportGraph"],
    )
    assert result["status"] == "success"
    assert len(result["graphs"]) == 1
    assert result["graphs"][0]["graph_name"] == "TransportGraph"
    assert result["graphs"][0]["metadata"]["nodeTables"][0]["name"] == "Nodes"


def test_doctor_checks_handle_failures_gracefully():
  """Verifies preflight doctor check returns structured remediation on missing project."""
  empty_settings = config.Settings(
      project_id="",
      spanner_project_id="",
      google_cloud_location="global",
      spanner_location="europe-west1",
      spanner_instance_id="transport-graph-instance",
      spanner_database_id="transport-graph",
      spanner_graph_ids=("TransportGraph",),
      query_data_api_version="v1alpha",
      query_data_location="us-central1",
      query_data_execute_query=True,
      query_data_include_raw=False,
      gemini_model="gemini-3.8-flash",
      nl2gql_backend="querydata",
  )
  res, token = doctor.check_credentials_and_project(empty_settings)
  assert res.status == "fail"
  assert token is None
  assert res.remediation != ""


def test_web_server_endpoints(tmp_path, monkeypatch):
  """Verifies FastAPI web endpoints (/healthz, /api/config, /api/topology, /api/sessions, /)."""
  monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
  monkeypatch.delenv("SAMPLE_PROMPTS_FILE", raising=False)
  monkeypatch.delenv("TOPOLOGY_FILE", raising=False)
  monkeypatch.delenv("SHOW_SAMPLE_PROMPTS", raising=False)
  monkeypatch.delenv("QUERY_DATA_EXECUTE_QUERY", raising=False)
  client = TestClient(web_server.app)

  # 1. Index HTML
  resp_index = client.get("/")
  assert resp_index.status_code == 200
  assert "TransportGraph Console" in resp_index.text
  assert "env-project-badge" not in resp_index.text

  # 2. Healthz
  resp_health = client.get("/healthz")
  assert resp_health.status_code == 200
  assert resp_health.json()["status"] == "ok"

  # 3. Config & Generic Sample Prompts + Default Flags
  resp_cfg = client.get(
      "/api/config",
      headers={"X-Goog-Authenticated-User-Email": "accounts.google.com:alice@example.com"},
  )
  assert resp_cfg.status_code == 200
  cfg_data = resp_cfg.json()
  assert cfg_data["user_email"] == "alice@example.com"
  assert cfg_data["query_data_execute_query"] is True
  assert cfg_data["show_sample_prompts"] is True
  assert len(cfg_data["sample_prompts"]) >= 2
  assert cfg_data["sample_prompts"][0]["category"] == "Graph Schema & Discovery"

  # 4. External SAMPLE_PROMPTS_FILE and SHOW_SAMPLE_PROMPTS=false override
  custom_prompts_file = tmp_path / "custom_prompts.json"
  custom_prompts_file.write_text(
      json.dumps([{"category": "Custom Category", "prompts": ["Custom prompt 1"]}]),
      encoding="utf-8",
  )
  monkeypatch.setenv("SAMPLE_PROMPTS_FILE", str(custom_prompts_file))
  monkeypatch.setenv("SHOW_SAMPLE_PROMPTS", "false")
  resp_custom_cfg = client.get("/api/config")
  assert resp_custom_cfg.status_code == 200
  assert resp_custom_cfg.json()["sample_prompts"][0]["category"] == "Custom Category"
  assert resp_custom_cfg.json()["show_sample_prompts"] is False
  monkeypatch.delenv("SAMPLE_PROMPTS_FILE", raising=False)
  monkeypatch.delenv("SHOW_SAMPLE_PROMPTS", raising=False)

  # 5. Topology (empty by default unless TOPOLOGY_FILE / local_data/topology.json is present)
  resp_topo = client.get("/api/topology")
  assert resp_topo.status_code == 200
  topo_data = resp_topo.json()
  assert topo_data["graph_id"] == "TransportGraph"
  assert topo_data["nodes"] == []
  assert topo_data["links"] == []

  # 6. CSRF header check on POST /api/sessions
  resp_no_csrf = client.post("/api/sessions", json={})
  assert resp_no_csrf.status_code == 400

  resp_session = client.post(
      "/api/sessions",
      headers={"X-Requested-With": "pytest"},
      json={"execute_query": True},
  )
  assert resp_session.status_code == 200
  session_data = resp_session.json()
  assert "session_id" in session_data
  assert session_data["execute_query"] is True


@pytest.mark.integration
@INTEGRATION_SKIP
def test_live_spanner_graph_queries():
  """Verifies the Cloud Spanner Property Graph is present in INFORMATION_SCHEMA."""
  settings = config.get_settings()
  client = spanner.Client(project=settings.spanner_project_id)
  instance = client.instance(settings.spanner_instance_id)
  database = instance.database(settings.spanner_database_id)

  sql_graphs = """
  SELECT PROPERTY_GRAPH_NAME, TO_JSON_STRING(PROPERTY_GRAPH_METADATA_JSON)
  FROM INFORMATION_SCHEMA.PROPERTY_GRAPHS
  """
  with database.snapshot() as snapshot:
    rows = {row[0]: json.loads(row[1]) for row in snapshot.execute_sql(sql_graphs)}

  for graph_id in settings.spanner_graph_ids:
    assert graph_id in rows
    assert len(rows[graph_id].get("nodeTables") or []) > 0


@pytest.mark.integration
@INTEGRATION_SKIP
@pytest.mark.asyncio
async def test_live_adk_agent_end_to_end():
  """Runs an end-to-end conversational turn through the ADK Nl2GqlAgent."""
  agent = nl2gql_agent_module.Nl2GqlAgent()
  runner = InMemoryRunner(agent=agent, app_name="graph_test_app")
  session = await runner.session_service.create_session(
      app_name="graph_test_app",
      user_id="test_user",
  )

  user_msg = types.Content(
      role="user",
      parts=[
          types.Part.from_text(
              text="What node types exist in the graph, and how many nodes are there?"
          )
      ],
  )

  final_text_parts: list[str] = []
  async for event in runner.run_async(
      user_id="test_user",
      session_id=session.id,
      new_message=user_msg,
  ):
    if event.content and event.content.parts:
      for part in event.content.parts:
        if part.text:
          final_text_parts.append(part.text)

  full_response = "\n".join(final_text_parts)
  assert len(full_response.strip()) > 0


@pytest.mark.integration
@INTEGRATION_SKIP
def test_live_web_chat_sse_stream():
  """Verifies end-to-end SSE streaming through the FastAPI /api/chat endpoint."""
  client = TestClient(web_server.app)
  with client.stream(
      "POST",
      "/api/chat",
      headers={"X-Requested-With": "pytest"},
      json={
          "message": "Show a sample of nodes in the graph.",
          "execute_query": False,
      },
  ) as resp:
    assert resp.status_code == 200
    events = []
    for line in resp.iter_lines():
      if line.startswith("data: "):
        events.append(json.loads(line[6:]))

  event_types = [e["type"] for e in events]
  assert "session" in event_types
  assert "tool_call" in event_types
  assert "tool_result" in event_types
  assert "text" in event_types
  assert "done" in event_types
