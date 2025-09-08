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
from typing import Any, Dict, List, Optional

from anyio.abc import TaskGroup  # typing-friendly protocol for TaskGroup
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from langchain_core.messages import SystemMessage, BaseMessage, AnyMessage
import yaml

from app.common.kf_base_client import KfResourceNotFoundError, KfServiceUnavailable
from app.common.kf_resource_client import KfResourceClient
from app.common.structures import AgentSettings
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
        self.tag = agent_settings.tag
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
        self._resource_client = KfResourceClient()
        self._agent_binding: Optional[Dict] = None

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

    def __str__(self) -> str:
        """Human-friendly identifier."""
        return f"{self.name} ({self.nickname}): {self.description}"


    async def load_agent_configuration(self, fallback_prompt_func):
        """
        Loads the agent's binding and resolves the system prompt.

        Args:
            fallback_prompt_func: A function to call if the database lookup fails.
        """
        try:
            binding_resource: Optional[Dict[str, Any]] = self._resource_client.get_resource(id=self.tag)

            if binding_resource is None:
                raise KfResourceNotFoundError(f"Agent binding '{self.tag}' not found.")
            
            # Use explicit type checking and defensive access.
            content_str = binding_resource.get("content", "")
            if not isinstance(content_str, str) or not content_str:
                raise ValueError("Agent binding content is empty or malformed.")
            
            # The split will always return at least one element. We check for a second one.
            parts = content_str.split('---', 2)
            if len(parts) < 3:
                raise ValueError("Agent binding content is malformed.")
            
            self._agent_binding = yaml.safe_load(parts[-1])
            if not isinstance(self._agent_binding, dict):
                raise ValueError("Agent binding YAML is not a valid dictionary.")

            system_prompt_id = self._agent_binding.get("system_prompt_id")
            if not isinstance(system_prompt_id, str) or not system_prompt_id:
                raise ValueError("System prompt ID is missing or not a string.")
                
            prompt_resource: Optional[Dict[str, Any]] = self._resource_client.get_resource(id=system_prompt_id)
            if prompt_resource is None:
                raise KfResourceNotFoundError(f"Prompt with ID '{system_prompt_id}' not found.")
            
            prompt_content = prompt_resource.get("content")
            if not isinstance(prompt_content, str) or not prompt_content:
                raise ValueError("System prompt content is empty or not a string.")
            
            self.base_prompt = prompt_content
            logger.info(f"Loaded agent '{self.name}' with system prompt from '{system_prompt_id}'.")

        except (KfServiceUnavailable, KfResourceNotFoundError, ValueError, yaml.YAMLError) as e:
            logger.warning(
                f"Could not load binding or prompt for '{self.name}'. "
                f"Using default fallback. Error: {e}"
            )
            self.base_prompt = fallback_prompt_func()


    def get_node_prompt(self, node_key: str) -> Optional[str]:
        """
        Returns the specific prompt for a given node, if an override exists.
        
        Args:
            node_key: The unique identifier for the graph node (e.g., 'reasoner', 'rephrase_query').
        
        Returns:
            The prompt content string or None if no override is found.
        """
        if self._agent_binding is None:
            return None

        node_overrides: Optional[List[Dict[str, Any]]] = self._agent_binding.get("node_overrides")
        if not isinstance(node_overrides, list):
            return None

        for override in node_overrides:
            if override.get("node_key") == node_key:
                prompt_id = override.get("prompt_id")
                if isinstance(prompt_id, str):
                    try:
                        prompt_resource: Optional[Dict[str, Any]] = self._resource_client.get_resource(id=prompt_id)
                        if isinstance(prompt_resource, dict):
                            content = prompt_resource.get("content")
                            if isinstance(content, str):
                                return content
                    except (KfServiceUnavailable, KfResourceNotFoundError, yaml.YAMLError) as e:
                        logger.warning(
                            f"Failed to fetch override prompt for node '{node_key}'. Error: {e}"
                        )
                return None
        return None

    async def compose_messages(
        self,
        node_key: str,
        messages: List[AnyMessage],
        context: Optional[str] = None
    ) -> List[BaseMessage]:
        """
        Generates a final list of messages for the LLM by combining:
        1. An optional node-specific system prompt (from the binding).
        2. The agent's global system prompt (base_prompt).
        3. The provided user messages.
        
        Args:
            node_key: The identifier for the current node, used to find overrides.
            messages: The list of user/assistant messages for the turn.
            context: An optional string to be added to the system prompt (e.g., from tools).
        
        Returns:
            A new list of messages with the system prompts prepended.
        """
        system_prompt_text: str = self.base_prompt
        
        node_prompt_content: Optional[str] = self.get_node_prompt(node_key)
        if node_prompt_content:
            system_prompt_text = f"{node_prompt_content}\n\n{system_prompt_text}"
        
        if context:
            system_prompt_text = f"{system_prompt_text}\n\n{context}"
        
        return [SystemMessage(content=system_prompt_text), *messages]