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

import asyncio
import importlib
import logging
from inspect import iscoroutinefunction
from typing import Callable, Dict, List, Type
import anyio
from anyio.abc import TaskGroup

from app.application_context import get_knowledge_flow_base_url
from app.common.structures import AgentSettings, Configuration
from app.core.agents.agent_loader import AgentLoader
from app.core.agents.agent_supervisor import AgentSupervisor
from app.core.agents.agentic_flow import AgenticFlow
from app.core.agents.flow import AgentFlow
from app.core.agents.runtime_context import RuntimeContext
from app.core.agents.store.base_agent_store import BaseAgentStore

logger = logging.getLogger(__name__)
SUPPORTED_TRANSPORTS = ["sse", "stdio", "streamable_http", "websocket"]


class AgentManager:
    """
    Manages the full lifecycle of AI agents (leaders and experts), including:

    - Loading static agents from configuration at startup.
    - Persisting new agents to storage (e.g., DuckDB).
    - Rehydrating all persisted agents at runtime (with class instantiation and async init).
    - Registering agents into in-memory maps for routing and discovery.
    - Injecting expert agents into leader agents.
    - Providing runtime agent discovery (e.g., for the UI).

    Supports both statically declared agents (via configuration.yaml) and dynamically created ones.
    """

    def __init__(self, config: Configuration, store: BaseAgentStore):
        self.config = config
        self.store = store
        self.loader = AgentLoader(config=self.config, store=self.store)
        self.supervisor = AgentSupervisor()
        self._tg: TaskGroup | None = None
        self.agent_constructors: Dict[str, Callable[[], AgentFlow]] = {}
        self.agent_classes: Dict[str, Type[AgentFlow]] = {}
        self.agent_settings: Dict[str, AgentSettings] = {}
        self.failed_agents: Dict[str, AgentSettings] = {}
        # Retry loop lifecycle controls:
        # TG path (preferred): we hold a CancelScope.
        # Fallback path: detached asyncio.Task (still closeable via aclose()).
        self._retry_scope: anyio.CancelScope | None = None
        self._retry_task: asyncio.Task | None = None

    def start_retry_loop(self, tg: TaskGroup | None = None):
        if tg is None:
            return

        async def _retry_once():
            if not self.failed_agents:
                return
            to_remove = []
            for name, agent_cfg in list(self.failed_agents.items()):
                success = await self._register_static_agent(agent_cfg)
                if success:
                    # start long-lived work for the recovered agent
                    if self._tg is not None:
                        try:
                            inst = self.get_agent_instance(name)
                            await self.supervisor.start_agents(self._tg, [inst])
                        except Exception:
                            logger.exception("Failed to start recovered agent %s", name)
                    to_remove.append(name)
            for n in to_remove:
                del self.failed_agents[n]

        self.supervisor.start_retry_loop(tg, _retry_once)

    async def load_agents(self, tg: TaskGroup | None = None):
        """
        Orchestrate initial load:
        - static (from config)
        - persisted (from store)
        - resource-backed (from Knowledge-Flow)
        Then inject experts into leaders.
        """
        if tg is not None:
            self._tg = tg
        # 1) STATIC
        static_instances, failed = await self.loader.load_static()
        self.failed_agents.update(failed)
        for inst in static_instances:
            self._register_loaded_agent(inst.name, inst, inst.agent_settings)

        if tg:
            await self.supervisor.start_agents(tg, static_instances)
        # 2) PERSISTED
        persisted_instances = await self.loader.load_persisted()
        for inst in persisted_instances:
            # Avoid double-register if same name was in static set
            if inst.name in self.agent_settings:
                logger.debug("Persisted '%s' already registered; skipping.", inst.name)
                continue
            self._register_loaded_agent(inst.name, inst, inst.agent_settings)
        if tg:
            # only start the ones actually registered
            await self.supervisor.start_agents(
                tg, [a for a in persisted_instances if a.name in self.agent_settings]
            )

        # 3) RESOURCE-BACKED (Knowledge-Flow)
        resource_instances, to_replace = await self.loader.load_resource_agents(
            base_url=get_knowledge_flow_base_url(),
            type_to_class={"mcp": "app.core.agents.mcp_agent.MCPAgent"},
            existing_settings=self.agent_settings,  # <-- for updated_at compare
        )

        # Close+unregister replaced names (best effort)
        for name in to_replace:
            try:
                inst = self.get_agent_instance(name)
                if hasattr(inst, "aclose") and iscoroutinefunction(inst.aclose):
                    await inst.aclose()
            except Exception:
                logger.debug("aclose failed for %s (ignored).", name)
            await self.unregister_agent(name)

        # Register & start new/updated resource instances
        for inst in resource_instances:
            self.register_dynamic_agent(inst, inst.agent_settings)
        if tg:
            await self.supervisor.start_agents(tg, resource_instances)

        self.supervisor.inject_leaders(
            agents_by_name={
                n: self.get_agent_instance(n) for n in self.agent_constructors
            },
            settings_by_name=self.agent_settings,
            classes_by_name=self.agent_classes,
        )

    async def _register_static_agent(self, agent_cfg: AgentSettings) -> bool:
        try:
            module_name, class_name = agent_cfg.class_path.rsplit(".", 1)
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
        except (ValueError, ImportError, AttributeError) as e:
            logger.error(
                f"❌ Failed to import class '{agent_cfg.class_path}' for '{agent_cfg.name}': {e}"
            )
            return False

        if not issubclass(cls, (AgentFlow)):
            logger.error(
                f"Class '{agent_cfg.class_path}' is not a supported Flow or AgentFlow."
            )
            return False

        try:
            instance = cls(agent_settings=agent_cfg)
            if iscoroutinefunction(getattr(instance, "async_init", None)):
                await instance.async_init()

            self._register_loaded_agent(agent_cfg.name, instance, agent_cfg)
            logger.info(
                f"✅ Registered static agent '{agent_cfg.name}' from configuration."
            )
            return True
        except Exception as e:
            logger.error(
                f"❌ Failed to instantiate or register static agent '{agent_cfg.name}': {e}"
            )
            return False

    def _try_seed_agent(self, agent_cfg: AgentSettings):
        """
        Attempts to load the class for the given agent and instantiate it.
        If successful, saves it to persistent store.
        Logs detailed errors for class import/instantiation issues.
        """
        try:
            module_name, class_name = agent_cfg.class_path.rsplit(".", 1)
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
        except (ValueError, ImportError, AttributeError) as e:
            logger.error(
                f"❌ Failed to load class '{agent_cfg.class_path}' for '{agent_cfg.name}': {e}"
            )
            return

        if not issubclass(cls, (AgentFlow)):
            logger.error(
                f"Class '{agent_cfg.class_path}' is not a supported Flow or AgentFlow."
            )
            return

        try:
            cls(agent_settings=agent_cfg)  # Validate constructor works
        except Exception as e:
            logger.error(f"❌ Failed to instantiate '{agent_cfg.name}': {e}")
            return

        try:
            self.store.save(agent_cfg)
            logger.info(f"✅ Seeded agent '{agent_cfg.name}' from config into storage.")
        except Exception as e:
            logger.error(f"❌ Failed to save agent '{agent_cfg.name}': {e}")

    def _register_loaded_agent(
        self, name: str, instance: AgentFlow, settings: AgentSettings
    ):
        """
        Internal helper: registers an already-initialized agent (typically at startup).
        Adds it to the runtime maps so it's discoverable and usable.
        """
        self.agent_constructors[name] = lambda a=instance: a
        self.agent_classes[name] = type(instance)
        self.agent_settings[name] = settings

    def register_dynamic_agent(self, instance: AgentFlow, settings: AgentSettings):
        """
        Public method to register a dynamically created agent (e.g., via POST /agents/create).
        This makes the agent immediately available in the running app (UI, routing, etc).

        Should be called after the agent has been fully initialized (including async_init).
        """
        name = settings.name
        self.agent_constructors[name] = lambda a=instance: a
        self.agent_classes[name] = type(instance)
        self.agent_settings[name] = settings
        logger.info(
            f"✅ Registered dynamic agent '{name}' ({type(instance).__name__}) in memory."
        )

    async def unregister_agent(self, name: str):
        """
        Removes an agent from memory. Does NOT affect persisted storage.
        Ensures long-lived tasks are stopped before dropping references.
        """
        try:
            agent = self.get_agent_instance(name)
            close = getattr(agent, "aclose", None)
            if close and iscoroutinefunction(close):
                # best-effort; do not fail unregister on cleanup issues
                await close()
        except Exception:
            logger.debug("Unregister: aclose for %s failed/ignored.", name)
        self.agent_constructors.pop(name, None)
        self.agent_classes.pop(name, None)
        self.agent_settings.pop(name, None)
        logger.info(f"🗑️ Unregistered agent '{name}' from memory.")

    def get_agentic_flows(self) -> List[AgenticFlow]:
        """
        Returns a list of all expert agents (AgentFlows) that are currently registered.
        Used by the frontend to display selectable agents.
        """
        flows = []
        for name, constructor in self.agent_constructors.items():
            instance = constructor()
            flows.append(
                AgenticFlow(
                    name=instance.name,
                    role=instance.role,
                    nickname=instance.nickname,
                    description=instance.description,
                    icon=instance.icon,
                    tag=instance.tag,
                    experts=[],
                )
            )
        return flows

    def get_agent_instance(
        self, name: str, runtime_context: RuntimeContext | None = None
    ) -> AgentFlow:
        constructor = self.agent_constructors.get(name)
        if not constructor:
            raise ValueError(f"No agent constructor for '{name}'")
        instance = constructor()

        # Inject runtime context if provided and supported
        if runtime_context:
            instance.set_runtime_context(runtime_context)

        return instance

    def get_agent_settings(self, name: str) -> AgentSettings:
        settings = self.agent_settings.get(name)
        if not settings:
            raise ValueError(f"No agent settings for '{name}'")
        return settings

    def get_agent_classes(self) -> Dict[str, Type[AgentFlow]]:
        return self.agent_classes

    def get_enabled_agent_names(self) -> List[str]:
        return list(self.agent_constructors.keys())

    async def aclose(self):
        # Close all registered agents via supervisor
        await self.supervisor.close_agents(
            [self.get_agent_instance(n) for n in list(self.agent_constructors.keys())]
        )
        self.supervisor.stop_retry_loop()
