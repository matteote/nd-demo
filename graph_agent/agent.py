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

"""NL2GQL Conversational Query ADK Agent for Cloud Spanner TransportGraph."""

from typing import Any

import google.auth
from google.adk.agents import llm_agent
from google.adk.models import base_llm
from google.adk.models.google_llm import Gemini
from google.adk.tools.google_tool import GoogleTool
from google.adk.tools.spanner import query_tool
from google.adk.tools.spanner.settings import Capabilities
from google.adk.tools.spanner.settings import SpannerToolSettings
from google.adk.tools.tool_context import ToolContext

from . import config
from . import graph_schema_tool
from . import query_data_tool

_INITIAL_SETTINGS = config.get_settings()
DEFAULT_MODEL_NAME = _INITIAL_SETTINGS.gemini_model

_DEFAULT_INSTRUCTION = """\
You are an expert Graph Database Conversational Assistant specializing in \
GoogleSQL GQL for Spanner Graph.

Your primary role is to help users query and analyze graph data by delegating \
query generation and schema semantics to the `query_graph_data` tool \
(targeting the Gemini Data Analytics `QueryData` endpoint).

Follow these guidelines:
1. When the user asks a question about graph entities, relationships, or analytical \
metrics, call the `query_graph_data` tool with the user's natural language prompt. \
Rely strictly on `query_graph_data` to resolve the schema and handle query semantics; \
do not invent or rewrite queries based on assumed schema details.
2. Inspect the result returned by `query_graph_data`:

   - If `query_executed_by_query_data` is `True`, summarize the `query_result` \
and/or `natural_language_answer` returned by `query_graph_data`.
   - If `query_executed_by_query_data` is `False` and a `generated_query` is \
returned, execute that exact `generated_query` against Cloud Spanner using the \
`execute_spanner_query` tool and present the results.
   - If `disambiguation_questions` are returned, prompt the user for clarification.
   - If `query_graph_data` returns an error (for example, when the project is not \
yet allowlisted for `QueryData` graph queries), call `inspect_graph_schema` to \
retrieve the live Property Graph definition from `INFORMATION_SCHEMA.PROPERTY_GRAPHS`, \
compose a read-only GQL query grounded strictly in that schema, and execute it \
using `execute_spanner_query`.
3. Keep answers clear, accurate, and grounded in the tool outputs.
"""

_GEMINI_FALLBACK_INSTRUCTION = """\
You are an expert Graph Database Conversational Assistant specializing in \
GoogleSQL GQL for Spanner Graph.

Follow these guidelines:
1. Call `inspect_graph_schema` first to retrieve the live Spanner Property Graph \
definition, labels, properties, edge directions, descriptions, and synonyms.
2. Translate the user's question into a read-only Spanner GQL query grounded \
strictly in the schema returned by `inspect_graph_schema`. Never use reserved \
ISO GQL path-mode keywords (`WALK`, `TRAIL`, `SIMPLE`, `ACYCLIC`) as unquoted \
variable names.
3. Execute the query against Cloud Spanner using `execute_spanner_query`. If a \
syntax error occurs, refine the query once and re-run `execute_spanner_query`.
4. Present the generated query and the results clearly and accurately.
"""


class Nl2GqlAgent(llm_agent.LlmAgent):
  """ADK Agent for conversational Spanner Graph querying via QueryData RPC (v1alpha) and direct Spanner execution."""

  generate_query_result: bool = True
  nl2gql_backend: str = "querydata"

  def __init__(
      self,
      model: base_llm.BaseLlm | str | None = None,
      name: str = "spanner_graph_nl2gql",
      instruction: str = "",
      tools: list[Any] | None = None,
      api_version: str | None = None,
      project_id: str | None = None,
      query_data_location: str | None = None,
      spanner_location: str | None = None,
      instance_id: str | None = None,
      database_id: str | None = None,
      graph_ids: list[str] | None = None,
      generate_query_result: bool | None = None,
      nl2gql_backend: str | None = None,
      **kwargs: Any,
  ):
    settings = config.get_settings(project_id)
    resolved_project_id = project_id or settings.spanner_project_id
    resolved_api_version = api_version or settings.query_data_api_version
    resolved_qd_location = query_data_location or settings.query_data_location
    resolved_spanner_location = spanner_location or settings.spanner_location
    resolved_instance_id = instance_id or settings.spanner_instance_id
    resolved_database_id = database_id or settings.spanner_database_id
    resolved_graph_ids = graph_ids or settings.graph_ids_list
    resolved_backend = (nl2gql_backend or settings.nl2gql_backend).lower()
    resolved_generate_query_result = (
        query_data_tool.get_default_generate_query_result()
        if generate_query_result is None
        else generate_query_result
    )

    if model is None:
      client_kwargs: dict[str, Any] = {
          "enterprise": True,
          "location": settings.google_cloud_location,
      }
      if resolved_project_id:
        client_kwargs["project"] = resolved_project_id
      model = Gemini(
          model=settings.gemini_model,
          client_kwargs=client_kwargs,
      )

    tools = list(tools) if tools else []

    def query_graph_data(
        prompt: str,
        context_set_id: str | None = None,
        execute_query: bool | None = None,
        tool_context: ToolContext | None = None,
    ) -> dict[str, Any]:
      """Queries graph data using natural language via Gemini Data Analytics QueryData RPC (v1alpha).

      Args:
          prompt: User question about the graph database.
          context_set_id: Optional context set ID for grounding.
          execute_query: Optional override for whether QueryData should execute the
              generated query on Spanner in addition to generating it. When omitted,
              uses session state `query_data_execute_query` or the agent's configured
              `generate_query_result` / `QUERY_DATA_EXECUTE_QUERY` setting.
          tool_context: Optional ADK tool context for reading per-session overrides.

      Returns:
          Dictionary with generated GQL query, execution results, and answers.
      """
      session_override = None
      if tool_context is not None and hasattr(tool_context, "state"):
        state_val = tool_context.state.get("query_data_execute_query")
        if isinstance(state_val, bool):
          session_override = state_val

      if execute_query is not None:
        should_execute = execute_query
      elif session_override is not None:
        should_execute = session_override
      else:
        should_execute = resolved_generate_query_result

      return query_data_tool.query_data(
          prompt=prompt,
          api_version=resolved_api_version,
          project_id=resolved_project_id,
          query_data_location=resolved_qd_location,
          spanner_location=resolved_spanner_location,
          instance_id=resolved_instance_id,
          database_id=resolved_database_id,
          graph_ids=resolved_graph_ids,
          context_set_id=context_set_id,
          generate_query_result=should_execute,
      )

    async def execute_spanner_query(
        query: str,
        tool_context: ToolContext,
    ) -> dict[str, Any]:
      """Executes a read-only GoogleSQL or GQL query directly against the Cloud Spanner database.

      Args:
          query: The GQL or GoogleSQL query string to execute against TransportGraph.
          tool_context: ADK tool execution context.

      Returns:
          Dictionary with status and query result rows.
      """
      active_project = (
          resolved_project_id or config.get_settings().spanner_project_id
      )
      if not active_project:
        return {
            "status": "error",
            "message": (
                "GCP project ID is not configured. Run ./setup.sh or set "
                "GOOGLE_CLOUD_PROJECT."
            ),
        }
      credentials, _ = google.auth.default(
          scopes=["https://www.googleapis.com/auth/cloud-platform"]
      )
      return await query_tool.execute_sql(
          project_id=active_project,
          instance_id=resolved_instance_id,
          database_id=resolved_database_id,
          query=query,
          credentials=credentials,
          settings=SpannerToolSettings(capabilities=[Capabilities.DATA_READ]),
          tool_context=tool_context,
      )

    def inspect_graph_schema() -> dict[str, Any]:
      """Fetches the Spanner Property Graph schema, node/edge labels, descriptions, and synonyms."""
      return graph_schema_tool.get_graph_schema(
          project_id=resolved_project_id,
          instance_id=resolved_instance_id,
          database_id=resolved_database_id,
          graph_ids=resolved_graph_ids,
      )

    if resolved_backend != "gemini":
      tools.append(GoogleTool(func=query_graph_data))
    tools.append(GoogleTool(func=execute_spanner_query))
    tools.append(GoogleTool(func=inspect_graph_schema))

    default_inst = (
        _GEMINI_FALLBACK_INSTRUCTION
        if resolved_backend == "gemini"
        else _DEFAULT_INSTRUCTION
    )

    super().__init__(
        model=model,
        name=name,
        instruction=instruction or default_inst,
        tools=tools,
        generate_query_result=resolved_generate_query_result,
        nl2gql_backend=resolved_backend,
        **kwargs,
    )


root_agent = Nl2GqlAgent()
