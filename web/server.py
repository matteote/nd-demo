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

"""FastAPI web server and SSE streaming endpoint for the Spanner Graph Agent."""

from __future__ import annotations

import json
from pathlib import Path
import time
import typing
from typing import Any
import uuid

from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.adk.events import Event
from google.adk.events import EventActions
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel
from pydantic import Field

from graph_agent import config
from graph_agent.agent import root_agent

APP_NAME = "spanner_graph_agent_web"
WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(
    title="TransportGraph — Spanner Graph Agent",
    description=(
        "Natural Language to Graph Query Language (NL2GQL) web interface "
        "powered by Google ADK, Cloud Spanner Graph, and Gemini Data Analytics."
    ),
    version="0.2.0",
)

if STATIC_DIR.exists():
  app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)


class CreateSessionRequest(BaseModel):
  execute_query: bool | None = None


class ChatRequest(BaseModel):
  session_id: str | None = Field(
      default=None, description="Existing ADK session ID, or omit to create one."
  )
  message: str = Field(..., min_length=1, description="User natural language prompt.")
  execute_query: bool | None = Field(
      default=None,
      description=(
          "Optional per-session override for QUERY_DATA_EXECUTE_QUERY "
          "(True = QueryData executes query directly; False = Spanner tool executes GQL)."
      ),
  )


# Empty default topology structure (can be populated via TOPOLOGY_FILE or topology.json)
DEFAULT_TOPOLOGY: dict[str, Any] = {
    "graph_id": "TransportGraph",
    "nodes": [],
    "ports": [],
    "termination_points": [],
    "links": [],
    "trails": [],
}


def resolve_user_id(iap_email_header: str | None) -> str:
  """Extracts authenticated user identity from IAP header or returns default."""
  if not iap_email_header:
    return "local-user"
  if ":" in iap_email_header:
    return iap_email_header.split(":", 1)[1].strip() or "local-user"
  return iap_email_header.strip() or "local-user"


def verify_csrf_header(x_requested_with: str | None) -> None:
  """Enforces custom header on state-changing or streaming POST requests."""
  if not x_requested_with:
    raise HTTPException(
        status_code=400,
        detail="Missing required 'X-Requested-With' header on POST request.",
    )


DEFAULT_SAMPLE_PROMPTS: list[dict[str, Any]] = [
    {
        "category": "Graph Schema & Discovery",
        "prompts": [
            "What node types and relationship types exist in the graph?",
            "Summarize the number of nodes for each label in the graph.",
            "Show a sample of 10 nodes and their properties.",
        ],
    },
    {
        "category": "Connectivity & Path Exploration",
        "prompts": [
            "Show a sample of connected node pairs and the edges between them.",
            "Which nodes have the highest number of connected edges?",
            "Find multi-hop paths connecting nodes in the graph.",
        ],
    },
]


def load_sample_prompts() -> list[dict[str, Any]]:
  """Loads categorized sample prompts from an optional external JSON file or returns generic defaults."""
  import os

  candidates: list[Path] = []
  env_file = os.getenv("SAMPLE_PROMPTS_FILE", "").strip()
  if env_file:
    candidates.append(Path(env_file))
  candidates.extend([
      config.REPO_ROOT / "local_data" / "sample_projects.json",
      config.REPO_ROOT / "local_data" / "sample_prompts.json",
      config.REPO_ROOT / "local_data" / "prompts.json",
      config.REPO_ROOT / "sample_projects.json",
      config.REPO_ROOT / "sample_prompts.json",
      config.REPO_ROOT / "prompts.json",
  ])

  for path in candidates:
    if path.is_file():
      try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sample_prompts"), list):
          data = data["sample_prompts"]
        if isinstance(data, list) and data:
          if all(isinstance(item, str) for item in data):
            return [{"category": "Sample Prompts", "prompts": data}]
          if all(isinstance(item, dict) for item in data):
            return data
      except (OSError, ValueError):
        pass

  return DEFAULT_SAMPLE_PROMPTS


def load_topology() -> dict[str, Any]:
  """Loads optional graph topology visualization data from an external JSON file if present."""
  import os

  candidates: list[Path] = []
  env_file = os.getenv("TOPOLOGY_FILE", "").strip()
  if env_file:
    candidates.append(Path(env_file))
  candidates.extend([
      config.REPO_ROOT / "local_data" / "topology.json",
      config.REPO_ROOT / "topology.json",
  ])

  for path in candidates:
    if path.is_file():
      try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
          return data
      except (OSError, ValueError):
        pass

  settings = config.get_settings()
  graph_id = settings.spanner_graph_ids[0] if settings.spanner_graph_ids else "TransportGraph"
  return {**DEFAULT_TOPOLOGY, "graph_id": graph_id}


def _extract_structured_tool_info(
    tool_name: str, response: dict[str, Any] | Any
) -> dict[str, Any]:
  """Extracts GQL code, tabular results, and matched entity IDs from a tool response."""
  extracted: dict[str, Any] = {"tool_name": tool_name}
  if not isinstance(response, dict):
    return extracted

  if response.get("status") == "error":
    extracted["error"] = response.get("error_message") or "Tool execution failed."
    return extracted

  # 1. query_graph_data (Gemini Data Analytics QueryData NL2GQL)
  if tool_name == "query_graph_data":
    if response.get("generated_query"):
      extracted["gql"] = response["generated_query"]
    if response.get("intent_explanation"):
      extracted["intent_explanation"] = response["intent_explanation"]
    if response.get("disambiguation_question"):
      extracted["disambiguation"] = response["disambiguation_question"]
    query_result = response.get("query_result")
    if isinstance(query_result, dict):
      cols = [
          c.get("name", f"col_{i}")
          for i, c in enumerate(query_result.get("columns") or [])
          if isinstance(c, dict)
      ]
      raw_rows = query_result.get("rows") or []
      rows: list[list[Any]] = []
      for r in raw_rows:
        if isinstance(r, dict) and "values" in r:
          rows.append([
              v.get("value") if isinstance(v, dict) else v for v in r["values"]
          ])
        elif isinstance(r, list):
          rows.append(r)
      if cols or rows:
        extracted["table"] = {
            "columns": cols,
            "rows": rows,
            "total_row_count": query_result.get("total_row_count", len(rows)),
        }

  # 2. execute_spanner_query / execute_sql (ADK Spanner toolset)
  elif tool_name in ("execute_spanner_query", "execute_sql"):
    rows_data = response.get("rows") or response.get("result")
    if isinstance(rows_data, list) and rows_data:
      if isinstance(rows_data[0], dict):
        cols = list(rows_data[0].keys())
        rows = [[row.get(c) for c in cols] for row in rows_data]
      elif isinstance(rows_data[0], (list, tuple)):
        cols = [f"col_{i + 1}" for i in range(len(rows_data[0]))]
        rows = [list(row) for row in rows_data]
      else:
        cols = ["value"]
        rows = [[r] for r in rows_data]
      extracted["table"] = {
          "columns": cols,
          "rows": rows,
          "total_row_count": len(rows),
      }

  # Scan serialized response for known topology entity IDs so the UI can highlight them
  topology = load_topology()
  serialized = json.dumps(response, default=str)
  highlighted_ids: list[str] = []
  for collection in ("nodes", "ports", "termination_points", "links", "trails"):
    for item in topology.get(collection, []):
      entity_id = item["id"]
      short_name = item.get("short_name")
      item_name = item.get("name")
      if (
          entity_id in serialized
          or (short_name and short_name in serialized)
          or (item_name and item_name in serialized)
      ):
        highlighted_ids.append(entity_id)

  if highlighted_ids:
    extracted["highlighted_entities"] = sorted(set(highlighted_ids))

  return extracted


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
  """Serves the single-page web interface."""
  return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
  """Lightweight health check endpoint for Cloud Run and preflight scripts."""
  settings = config.get_settings()
  return {
      "status": "ok",
      "project_id": settings.project_id,
      "spanner_project_id": settings.spanner_project_id,
      "spanner_instance_id": settings.spanner_instance_id,
      "spanner_database_id": settings.spanner_database_id,
      "spanner_graph_ids": list(settings.spanner_graph_ids),
      "nl2gql_backend": settings.nl2gql_backend,
  }


@app.get("/api/config")
async def get_app_config(
    x_goog_authenticated_user_email: str | None = Header(default=None),
) -> dict[str, Any]:
  """Returns active environment metadata, user identity, and categorized sample prompts."""
  settings = config.get_settings()
  user_id = resolve_user_id(x_goog_authenticated_user_email)
  return {
      "project_id": settings.project_id,
      "spanner_project_id": settings.spanner_project_id,
      "spanner_instance_id": settings.spanner_instance_id,
      "spanner_database_id": settings.spanner_database_id,
      "spanner_graph_ids": list(settings.spanner_graph_ids),
      "gemini_model": settings.gemini_model,
      "nl2gql_backend": settings.nl2gql_backend,
      "query_data_execute_query": settings.query_data_execute_query,
      "show_sample_prompts": settings.show_sample_prompts,
      "user_email": user_id,
      "sample_prompts": load_sample_prompts(),
  }


@app.get("/api/topology")
async def get_topology() -> dict[str, Any]:
  """Returns optional network topology for interactive visualization."""
  return load_topology()


@app.post("/api/sessions")
async def create_session(
    req: CreateSessionRequest | None = None,
    x_requested_with: str | None = Header(default=None),
    x_goog_authenticated_user_email: str | None = Header(default=None),
) -> dict[str, Any]:
  """Creates a fresh ADK conversation session."""
  verify_csrf_header(x_requested_with)
  settings = config.get_settings()
  user_id = resolve_user_id(x_goog_authenticated_user_email)
  execute_query = (
      req.execute_query
      if (req and req.execute_query is not None)
      else settings.query_data_execute_query
  )
  session = await runner.session_service.create_session(
      app_name=APP_NAME,
      user_id=user_id,
      session_id=str(uuid.uuid4()),
      state={"query_data_execute_query": bool(execute_query)},
  )
  return {
      "session_id": session.id,
      "user_id": user_id,
      "execute_query": bool(execute_query),
      "created_at": int(time.time() * 1000),
  }


@app.post("/api/chat")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    x_requested_with: str | None = Header(default=None),
    x_goog_authenticated_user_email: str | None = Header(default=None),
) -> StreamingResponse:
  """Streams ADK agent events (tool calls, GQL generation, SQL results, and answer) as SSE."""
  verify_csrf_header(x_requested_with)
  settings = config.get_settings()
  user_id = resolve_user_id(x_goog_authenticated_user_email)
  session_id = req.session_id or str(uuid.uuid4())

  session = await runner.session_service.get_session(
      app_name=APP_NAME, user_id=user_id, session_id=session_id
  )
  initial_exec = (
      req.execute_query
      if req.execute_query is not None
      else settings.query_data_execute_query
  )
  if session is None:
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state={"query_data_execute_query": bool(initial_exec)},
    )
  elif req.execute_query is not None:
    await runner.session_service.append_event(
        session=session,
        event=Event(
            author="user",
            actions=EventActions(
                state_delta={"query_data_execute_query": bool(req.execute_query)}
            ),
        ),
    )

  async def event_generator() -> typing.AsyncGenerator[str, None]:
    start_ts = time.perf_counter()
    yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

    user_content = types.Content(
        role="user", parts=[types.Part.from_text(text=req.message)]
    )

    # Track SQL passed to execute_sql so we can attach it to the tool_result
    pending_sql_by_call_id: dict[str, str] = {}

    try:
      async for event in runner.run_async(
          user_id=user_id,
          session_id=session_id,
          new_message=user_content,
      ):
        if await request.is_disconnected():
          break

        for fc in event.get_function_calls() or []:
          args_dict = dict(fc.args) if fc.args else {}
          if fc.name in ("execute_spanner_query", "execute_sql"):
            sql_text = args_dict.get("query") or args_dict.get("sql")
            if sql_text:
              pending_sql_by_call_id[fc.id or "last"] = str(sql_text)
          payload = {
              "type": "tool_call",
              "id": fc.id,
              "name": fc.name,
              "args": args_dict,
          }
          yield f"data: {json.dumps(payload, default=str)}\n\n"

        for fr in event.get_function_responses() or []:
          resp_dict = dict(fr.response) if isinstance(fr.response, dict) else {"result": fr.response}
          extracted = _extract_structured_tool_info(fr.name, resp_dict)
          if fr.name in ("execute_spanner_query", "execute_sql") and "gql" not in extracted:
            executed_sql = pending_sql_by_call_id.get(fr.id or "last")
            if executed_sql:
              extracted["executed_sql"] = executed_sql
          payload = {
              "type": "tool_result",
              "id": fr.id,
              "name": fr.name,
              "response": resp_dict,
              "extracted": extracted,
          }
          yield f"data: {json.dumps(payload, default=str)}\n\n"

        if event.content and event.content.parts:
          for part in event.content.parts:
            if getattr(part, "thought", False):
              continue
            if part.text:
              payload = {
                  "type": "text",
                  "content": part.text,
                  "partial": bool(getattr(event, "partial", False)),
              }
              yield f"data: {json.dumps(payload)}\n\n"

      elapsed_ms = int((time.perf_counter() - start_ts) * 1000)
      yield f"data: {json.dumps({'type': 'done', 'session_id': session_id, 'duration_ms': elapsed_ms})}\n\n"

    except Exception as exc:  # pylint: disable=broad-exception-caught
      error_msg = str(exc)
      remediation = (
          "Run `uv run python scripts/doctor.py` to verify your GCP credentials, "
          "Spanner instance, and Gemini Data Analytics permissions."
      )
      yield f"data: {json.dumps({'type': 'error', 'message': error_msg, 'remediation': remediation})}\n\n"

  return StreamingResponse(
      event_generator(),
      media_type="text/event-stream",
      headers={
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
          "X-Accel-Buffering": "no",
      },
  )
