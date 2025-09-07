# app/core/agents/mcp_agent.py
from __future__ import annotations

import json
import logging
from typing import List, Any, Dict

from anyio.abc import TaskGroup
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState
from langgraph.constants import START
from langgraph.prebuilt import tools_condition
from pydantic import TypeAdapter

from app.common.structures import AgentSettings
from app.core.agents.flow import AgentFlow
from app.core.model.model_factory import get_model
from app.common.mcp_runtime import MCPRuntime
from app.common.resilient_tool_node import make_resilient_tools_node

logger = logging.getLogger(__name__)


class MCPAgent(AgentFlow):
    """
    MCPAgent — dynamic agent template for MCP tools.

    Fred intent (lifecycle):
    - __init__:    *pure construction* (no I/O). Compose MCPRuntime & config only.
    - async_init:  build model + graph *without* dialing MCP so UI can create agents
                   even if Knowledge-Flow is down.
    - async_start: background-connect MCP and eagerly bind tools once available.
                   Failure is logged but non-fatal; the tools node can refresh/rebind
                   on demand during the first tool use (e.g., after a 401/timeout).
    - aclose:      structured shutdown (close MCP client & transports cleanly).

    This mirrors SentinelExpert so all agents behave the same under outages/timeouts.
    """

    # ---- Public metadata (UI/registry) ---------------------------------------------
    name: str = "MCPExpert"
    nickname: str = "Mitch"
    role: str = "MCP Expert"
    description: str = "Agent dynamically created to use MCP-based tools."
    icon: str = "agent_generic"
    categories: List[str] = ["MCP"]
    tag: str = "mcp"

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
            # If you later add tenant/time filters, return them here.
            # ContextAwareTool will inject conservatively (schema-aware).
            context_provider=(lambda: self.get_runtime_context()),
        )
        # Helpful when normalizing varied ToolMessage payload shapes in responses.
        self._any_list_adapter: TypeAdapter[List[Any]] = TypeAdapter(List[Any])

    async def async_init(self):
        """
        Build model and graph WITHOUT dialing MCP.

        Why?
        - Allows dynamic agent creation even if Knowledge-Flow is offline.
        - The tools node uses a refresh callback; first tool use can (re)bind tools on demand.
        """
        self.model = get_model(self.agent_settings.model)
        self._graph = self._build_graph()

    async def async_start(self, tg: TaskGroup) -> None:
        """
        Bring MCP up in the background and bind tools once.

        Why background (tg.start_soon)?
        - Do not block app readiness / UI responsiveness on remote services.
        - Keep the task under the app's task group (structured concurrency):
          shutdown/cancellation is handled by the parent.
        """

        async def _bringup():
            try:
                await self.mcp.init()  # one connect only
                # Eager first bind improves first-use latency; later refreshes rebind again.
                self.model = self.model.bind_tools(self.mcp.get_tools())
                logger.info("%s: MCP bring-up complete; tools bound.", self.name)
            except Exception:
                # Non-fatal. Resilient ToolNode will refresh_and_bind on first use.
                logger.info(
                    "%s: MCP bring-up skipped (Knowledge-Flow unavailable); will refresh on demand.",
                    self.name,
                    exc_info=True,
                )

        tg.start_soon(_bringup)

    async def aclose(self):
        """
        Clean shutdown hook. Called by AgentManager/Supervisor from the SAME task.

        Why explicit close?
        - Ensures MCP transports & background tasks are torn down cleanly (no leaks).
        """
        await self.mcp.aclose()

    # ---- Execution ------------------------------------------------------------------
    def _base_prompt(self) -> str:
        return f"{self.base_prompt}\n\nThe current date is {self.current_date}."

    async def reasoner(self, state: MessagesState):
        """
        One LLM step; may call MCP tools.
        After tools run, collect ToolMessages and attach normalized payloads to response metadata.
        Why attach here?
        - Keeps UI decoupled from tool payload shapes and gives devs quick introspection.
        """
        if self.model is None:
            raise RuntimeError(
                "Model is not initialized. Did you forget to call async_init()?"
            )

        try:
            response = await self.model.ainvoke(
                [self._base_prompt()] + state["messages"]
            )

            # Optional: attach last payload per tool to response metadata (handy in UI)
            tool_payloads: Dict[str, Any] = {}
            for msg in state["messages"]:
                if isinstance(msg, ToolMessage):
                    tool_name: str | None = msg.name
                    if not tool_name:
                        continue  # skip nameless tool messages
                    raw = msg.content
                    try:
                        tool_payloads[tool_name] = (
                            json.loads(raw) if isinstance(raw, str) else raw
                        )
                    except Exception:
                        tool_payloads[tool_name] = raw
            existing = response.response_metadata.get("tools", {})
            existing.update(tool_payloads)
            response.response_metadata["tools"] = existing

            return {"messages": [response]}

        except Exception:
            logger.exception("%s: unexpected error during reasoning", self.name)
            fallback = await self.model.ainvoke(
                [HumanMessage(content="An error occurred.")]
            )
            return {"messages": [fallback]}

    # ---- Graph ----------------------------------------------------------------------
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
            # Resilient ToolNode calls this after timeouts/401/ClosedResourceError.
            self.model = await self.mcp.refresh_and_bind(self.model)

        tools_node = make_resilient_tools_node(
            get_tools=self.mcp.get_tools,  # live accessor; don't capture lists
            refresh_cb=_refresh_and_rebind,
        )

        builder.add_node("tools", tools_node)
        builder.add_edge(START, "reasoner")
        builder.add_conditional_edges("reasoner", tools_condition)
        builder.add_edge("tools", "reasoner")
        return builder

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base_prompt": self.base_prompt,
            "role": self.role,
            "nickname": self.nickname,
            "description": self.description,
            "icon": self.icon,
            "categories": self.categories,
            "tag": self.tag,
        }
