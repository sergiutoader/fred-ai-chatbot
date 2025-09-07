# Copyright Thales 2025
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
AgentFlow — the base class for LangGraph-based agents in Fred.

# Lifecycle (API contract)

- __init__(settings):            Pure, sync setup only (no I/O).
- async_init():                  Bounded async setup (graph/model/tool binding). No loops.
- async_start(tg):               Start long-lived work (streams/pollers) under app TaskGroup.
- aclose():                      Async cleanup (same task as shutdown), idempotent.

Rationale:
- We keep `async_init()` for “one-shot, fast” async work (e.g., MCP tool discovery, graph build).
- We keep `async_start()` for anything that continues running (SSE/WebSocket/HTTP2, retries).
- We use `aclose()` (not `async_close`) to align with Python async ecosystem (e.g., httpx.AsyncClient.aclose()).

Public surface:
- Lifecycle: __init__, async_init, async_start, aclose
- Execution helpers: get_compiled_graph, use_fred_prompts
- Context: set_runtime_context, get_runtime_context
- Visualization: save_graph_image
"""

from abc import abstractmethod
from datetime import datetime
import logging
from typing import List, Optional, Sequence

from anyio.abc import TaskGroup  # typing-friendly protocol for TaskGroup
from IPython.display import Image
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import SystemMessage, BaseMessage

from app.common.structures import AgentSettings
from app.core.agents.agent_state import Prepared, resolve_prepared
from app.application_context import get_knowledge_flow_base_url
from app.core.agents.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)


class AgentFlow:
    """
    Base class for LangGraph-based AI agents.

    What an AgentFlow is:
    - A small object that holds metadata, prompt, model bindings, and a LangGraph.
    - A predictable lifecycle with clear separation between bounded setup and long-lived work.

    Subclass responsibilities:
    - In __init__: store settings; no awaiting or I/O.
    - In async_init(): create/bind model & tools, build your LangGraph into `self._graph`.
    - (Optionally) in async_start(tg): start persistent work (streams, watchers) under `tg`.
    - (Optionally) in aclose(): close sockets/clients, cancel scopes, flush state.

    Execution:
    - Call `get_compiled_graph()` to compile your graph once and reuse it.
    - Use `use_fred_prompts()` to prepend UI-selected prompts as a single SystemMessage.
    """

    # Class attributes for documentation/metadata (subclasses typically override)
    name: str
    role: str
    nickname: str
    description: str
    icon: str
    tag: str
    categories: List[str] = []

    # -------------------------
    # Public API (top section)
    # -------------------------

    def __init__(self, agent_settings: AgentSettings):
        """
        Pure sync constructor — no network, no awaits.

        Args:
            agent_settings: AgentSettings with core metadata (name, role, prompts, etc.).
        """
        self.agent_settings = agent_settings

        # Display/metadata (fall back to class defaults if not set)
        self.name = agent_settings.name
        self.nickname = agent_settings.nickname or agent_settings.name
        self.role = agent_settings.role or getattr(self.__class__, "role", "")
        self.description = agent_settings.description or getattr(
            self.__class__, "description", ""
        )
        self.icon = getattr(self.__class__, "icon", "")
        self.tag = agent_settings.tag or getattr(self.__class__, "tag", "")
        self.categories = agent_settings.categories or getattr(
            self.__class__, "categories", []
        )

        # Runtime fields populated during lifecycle
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.model = None  # set in async_init()
        self.base_prompt: str = ""  # set in async_init() or by subclass
        self._graph = None  # set in async_init() (LangGraph StateGraph)
        self.streaming_memory = MemorySaver()
        self.compiled_graph: Optional[CompiledStateGraph] = None
        self.runtime_context: Optional[RuntimeContext] = None
        self._started: bool = False  # guard to avoid double-start

    @abstractmethod
    async def async_init(self):
        """
        Bounded async setup: build your graph/model/tool bindings here.

        DO:
        - create the LLM/model
        - fetch MCP tool schemas (one-shot)
        - bind tools into the model
        - build the LangGraph into `self._graph`
        - set `self.base_prompt` if needed

        DO NOT:
        - start infinite loops
        - open persistent SSE/WebSocket/HTTP2 streams

        Those belong in `async_start(...)`.
        """
        ...

    async def async_start(self, tg: TaskGroup):
        """
        Start long-lived work under the app's TaskGroup (optional).

        Use when:
        - Your agent needs a background loop, stream, or watch that runs until shutdown.
        - You want Ctrl-C (or FastAPI shutdown) to cancel that work deterministically.

        Default: no-op. Subclasses override if needed.
        """
        if self._started:
            return
        self._started = True

    async def aclose(self):
        """
        Async cleanup (optional). Called from the SAME task as shutdown.

        Use to:
        - cancel CancelScopes,
        - close HTTP/WebSocket clients,
        - flush buffers/state.

        Default: no-op. Subclasses override if they own resources.
        """
        self._started = False

    def get_compiled_graph(self) -> CompiledStateGraph:
        """
        Compile and return the agent's LangGraph.

        Idempotent:
        - Compiles once with a streaming checkpointer (MemorySaver).
        - Returns the cached compiled graph later.
        """
        if self.compiled_graph is None:
            if self._graph is None:
                raise ValueError(
                    "Graph is not built. Did you forget to run async_init()?"
                )
            self.compiled_graph = self._graph.compile(
                checkpointer=self.streaming_memory
            )
        return self.compiled_graph

    def use_fred_prompts(self, messages: Sequence[BaseMessage]) -> List[BaseMessage]:
        """
        Merge UI-selected prompts + agent base_prompt into ONE SystemMessage.

        Why:
        - Keeps ordering/formatting stable and auditable.
        - Prevents “prompt soup” and surprise overrides.

        If nothing is selected, returns messages unchanged.
        """
        sys_text = self._compose_fred_system_text().strip()
        if not sys_text:
            return list(messages)
        return [SystemMessage(content=sys_text), *messages]

    def set_runtime_context(self, context: RuntimeContext) -> None:
        """
        Inject per-turn runtime context (e.g., tenant/library, time window).
        Agents that consult context should read it via `get_runtime_context()`.
        """
        self.runtime_context = context

    def get_runtime_context(self) -> Optional[RuntimeContext]:
        """
        Return the last runtime context set by the caller (may be None).
        """
        return self.runtime_context

    def save_graph_image(self, path: str):
        """
        Save this agent's compiled graph as a PNG (Mermaid-rendered).

        Args:
            path: Directory path where the image will be written (filename is `<name>.png`).
        """
        if self._graph is None:
            raise ValueError("Graph is not defined. Build it in async_init().")
        compiled_graph = self.get_compiled_graph()
        graph = Image(compiled_graph.get_graph().draw_mermaid_png())
        with open(f"{path}/{self.name}.png", "wb") as f:
            f.write(graph.data)

    def __str__(self) -> str:
        """Human-friendly identifier."""
        return f"{self.name} ({self.nickname}): {self.description}"

    # --------------------------------
    # Private helpers (below the fold)
    # --------------------------------

    def _compose_fred_system_text(self) -> str:
        """
        INTERNAL: Build the single SystemMessage contents from:
        - selected Fred prompt resources (via Knowledge-Flow),
        - this agent's `base_prompt`.

        Order is preserved: [selected prompts] then [base_prompt].
        """
        ctx = self.get_runtime_context() or RuntimeContext()
        prepared: Prepared = resolve_prepared(ctx, get_knowledge_flow_base_url())

        pre_text = (prepared.prompt_text or "").strip()
        base_text = (self.base_prompt or "").strip()
        if pre_text and base_text:
            return f"{pre_text}\n\n{base_text}"
        return pre_text or base_text
