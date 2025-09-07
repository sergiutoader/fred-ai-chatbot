# app/agents/sentinel/sentinel_expert.py
# Copyright Thales 2025
# Licensed under the Apache License, Version 2.0

import json
import logging
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.constants import START
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import tools_condition
from pydantic import TypeAdapter

from app.common.mcp_runtime import MCPRuntime
from app.common.resilient_tool_node import make_resilient_tools_node
from app.common.structures import AgentSettings
from app.core.agents.flow import AgentFlow
from app.core.model.model_factory import get_model

logger = logging.getLogger(__name__)


class SentinelExpert(AgentFlow):
    """
    Sentinel — Ops & Monitoring (OpenSearch + KPIs).

    Fred intent (lifecycle):
    - __init__:    *pure construction* (no I/O). Compose MCPRuntime & config only.
    - async_init:  build model + graph *without* dialing MCP so app can start even
                   if Knowledge-Flow is down.
    - async_start: background-connect MCP and eagerly bind tools once available.
                   Failure is logged but non-fatal; the tools node can refresh/rebind
                   on demand during the first tool use (e.g., after a 401/timeout).
    - aclose:      structured shutdown (close MCP client & transports cleanly).

    Why this split?
    - Keeps startup fast and robust to remote outages.
    - Ensures tool binding happens *once* at bring-up, while preserving the ability
      to rebind later via the resilient tools node.
    """

    # ---- Public metadata (shows up in UI/registry) ---------------------------------
    name: str = "SentinelExpert"
    nickname: str = "Samy"
    role: str = "Ops & Monitoring Expert"
    description: str = "Watches your instance and surfaces OpenSearch health & KPIs with actionable guidance."
    icon: str = "ops_agent"
    categories: list[str] = []
    tag: str = "ops"

    # ---- Lifecycle (API contract) ---------------------------------------------------
    def __init__(self, agent_settings: AgentSettings):
        """
        Construction-only: set fields; do not connect to MCP here.

        Why no I/O here?
        - __init__ must be cheap and deterministic (used by registries/DI).
        - Remote dependencies are started later under a task group for proper ownership.
        """
        super().__init__(agent_settings=agent_settings)
        self.mcp = MCPRuntime(
            agent_settings=self.agent_settings,
            # If you add tenant/time filters later, pass a context provider.
            # Rationale: ContextAwareTool inspects schema and injects 'tags' only
            # when supported. Keeping this lazy prevents surprising the LLM.
            context_provider=(lambda: self.get_runtime_context()),
        )
        # Tolerant adapter for varied tool payload shapes in ToolMessages.
        self._any_list_adapter: TypeAdapter[List[Any]] = TypeAdapter(List[Any])

    async def async_init(self):
        """
        Build model and graph WITHOUT dialing MCP.
        Rationale: let app start cleanly even if Knowledge-Flow is down.
        - The tools node is wired with a refresh callback; the first tool use can
          (re)bind tools on demand if bring-up hasn't happened yet.
        """
        self.model = get_model(self.agent_settings.model)
        # Do not bind tools yet; tools may not exist if MCP is offline.
        self._graph = self._build_graph()

    async def async_start(self, tg):
        """
        Bring MCP up in the background and bind tools once.

        Why background (tg.start_soon)?
        - Do not block app readiness on remote services.
        - Keep the task under the app's task group (structured concurrency): if the
          app shuts down or errors, this child is cancelled automatically.

        Why bind_tools here?
        - Eager first bind improves first-use latency.
        - Later, the resilient tools node may refresh MCP and we rebind again as needed.
        """

        async def _bringup():
            try:
                await self.mcp.init()  # one connect only
                self.model = self.model.bind_tools(self.mcp.get_tools())
                logger.info("%s: MCP bring-up complete; tools bound.", self.name)
            except Exception:
                logger.info(
                    "%s: MCP bring-up skipped (KF unavailable); will refresh on demand.",
                    self.name,
                    exc_info=True,
                )

        tg.start_soon(_bringup)

    async def aclose(self):
        """
        Clean shutdown hook. Called by AgentManager/Supervisor from the SAME task.
        """
        await self.mcp.aclose()

    # ---- Execution ------------------------------------------------------------------
    async def reasoner(self, state: MessagesState):
        """
        One LLM step; may call tools (kpi.* / os.*).
        After tools run, collect ToolMessages and attach normalized payloads to response metadata.
        """
        if self.model is None:
            raise RuntimeError(
                "Model is not initialized. Did you forget to call async_init()?"
            )

        try:
            response = self.model.invoke([self.base_prompt] + state["messages"])

            # Collect last payload per tool call
            tool_payloads: Dict[str, Any] = {}
            for msg in state["messages"]:
                if isinstance(msg, ToolMessage) and getattr(msg, "name", ""):
                    raw = msg.content
                    normalized = raw
                    if isinstance(raw, str):
                        try:
                            normalized = json.loads(raw)
                        except Exception:
                            normalized = raw  # keep raw string if not JSON
                    if msg.name is not None:
                        tool_payloads[msg.name] = normalized

            # Attach tool results to metadata for the UI
            existing = response.response_metadata.get("tools", {})
            existing.update(tool_payloads)
            response.response_metadata["tools"] = existing

            return {"messages": [response]}

        except Exception as e:
            logger.exception("Sentinel: unexpected error: %s", e)
            fallback = await self.model.ainvoke(
                [
                    HumanMessage(
                        content="An error occurred while checking the system. Please try again."
                    )
                ]
            )
            return {"messages": [fallback]}

    # ---- Private helpers -------------------------------------------------------------
    def _generate_prompt(self) -> str:
        return (
            "You are Sentinel, an operations and monitoring agent for the Fred platform.\n"
            "Use the available MCP tools to inspect OpenSearch health and KPIs.\n"
            "- Use os.* tools for cluster status, shards, indices, mappings, diagnostics.\n"
            "- Use kpi.* tools for usage, cost, latency, error rates.\n"
            "Return clear, actionable summaries with next steps when degraded.\n"
            "Add short markers like [os_health], [kpi_query] near tool-sourced facts.\n"
            "Prefer concise bullets and short tables when helpful.\n"
            f"Current date: {self.current_date}.\n"
        )

    def _build_graph(self) -> StateGraph:
        """
        Build the graph even if MCP tools are not ready.
        The tools node uses a refresh callback that:
          - refreshes MCP client/toolkit
          - rebinds tools into the model
        so first tool use (or async_start) will make tools available.
        """
        builder = StateGraph(MessagesState)
        builder.add_node("reasoner", self.reasoner)

        async def _refresh_and_rebind():
            self.model = await self.mcp.refresh_and_bind(self.model)

        # get_tools() may return [] if MCP not yet initialized; the resilient node handles that.
        tools_node = make_resilient_tools_node(
            get_tools=self.mcp.get_tools,
            refresh_cb=_refresh_and_rebind,
        )

        builder.add_node("tools", tools_node)
        builder.add_edge(START, "reasoner")
        builder.add_conditional_edges("reasoner", tools_condition)
        builder.add_edge("tools", "reasoner")
        return builder
