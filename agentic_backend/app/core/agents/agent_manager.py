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
from builtins import ExceptionGroup
from inspect import iscoroutinefunction
from typing import Callable, Dict, List, Type, Any, Optional
import importlib
import httpx
import yaml
from inspect import iscoroutinefunction
from hashlib import sha256
from app.common.structures import MCPServerConfiguration


from langchain_mcp_adapters.client import MultiServerMCPClient
from tenacity import RetryError, retry, stop_after_delay, wait_fixed

from app.agents.leader.leader import Leader
from app.application_context import get_configuration, get_knowledge_flow_base_url
from app.common.error import UnsupportedTransportError
from app.common.structures import AgentSettings, Configuration
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
        self.config = get_configuration()
        self.store = store

        self.agent_constructors: Dict[str, Callable[[], AgentFlow]] = {}
        self.agent_classes: Dict[str, Type[AgentFlow]] = {}
        self.agent_settings: Dict[str, AgentSettings] = {}
        self.failed_agents: Dict[str, AgentSettings] = {}
        self._retry_task: asyncio.Task | None = None

    def start_retry_loop(self):
        if self._retry_task is None:
            self._retry_task = asyncio.create_task(self._retry_failed_agents_loop())

    async def load_agents(self):
        """
        Called at application startup.
        - Seeds static agents from configuration.yaml if missing in storage.
        - Loads all persisted agents from DuckDB and instantiates them.
        - Registers them in memory and injects experts into leaders.
        """
        for agent_cfg in self.config.ai.agents:
            if not agent_cfg.enabled:
                continue
            success = await self._register_static_agent(agent_cfg)
            if not success:
                self.failed_agents[agent_cfg.name] = (
                    agent_cfg  # ✅ ensure failed ones are tracked
                )
        await self._load_all_persisted_agents()
        # NEW: load resource-backed agents
        await self.load_dynamic_resource_agents(
            base_url=get_knowledge_flow_base_url(),
            type_to_class={"mcp": "app.core.agents.mcp_agent.MCPAgent"}  # put your real class
        )
        self._inject_experts_into_leaders()
        
        
    async def load_dynamic_resource_agents(
        self,
        base_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        bearer_token: Optional[str] = None,
        timeout: float = 10.0,
        verify_tls: bool = True,
        replace_on_change: bool = True,
        type_to_class: Optional[Dict[str, str]] = None,
    ):
        """
        v1 loader with optional auth:
        - If `bearer_token` is provided, sets Authorization: Bearer <token>.
        - If `headers` is provided, merges them (takes precedence over bearer).
        - If neither is provided, calls the endpoint without auth.
        - `type_to_class` MUST be provided.
        """
        try:  # <- guard the whole loader so lifespan never explodes
            if type_to_class is None:
                logger.error(
                    "[ResourceAgents] Missing type_to_class mapping. "
                    "Pass e.g. type_to_class={'mcp': 'app.<your_module>.MCPAgent'}"
                )
                return
            logger.debug("[ResourceAgents] type_to_class mapping: %s", type_to_class)

            # Build headers
            req_headers: Dict[str, str] = {}
            if bearer_token:
                req_headers["Authorization"] = f"Bearer {bearer_token}"
            if headers:
                req_headers.update(headers)

            base = base_url.rstrip("/")
            logger.debug(
                "[ResourceAgents] start fetch base_url=%s path=/resources headers=%s bearer=%s",
                base, bool(req_headers), bool(bearer_token),
            )

            # Fetch resources
            async with httpx.AsyncClient(base_url=base, timeout=timeout, verify=verify_tls) as cli:
                try:
                    resp = await cli.get(
                        "/resources",
                        params={"kind": "agent"},
                        headers=req_headers or None,
                    )
                    logger.debug("[ResourceAgents] GET /resources -> status=%s", resp.status_code)
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    logger.warning(f"[ResourceAgents] fetch failed: {e.response.status_code} {e.response.text}")
                    return
                resources: List[Dict[str, Any]] = resp.json() or []
                logger.debug("[ResourceAgents] fetched %d resources", len(resources))

            if not resources:
                logger.warning("[ResourceAgents] no resources returned; check base_url/path/auth")
                return

            added, updated = 0, 0
            for idx, res in enumerate(resources):
                rid = res.get("id")
                logger.debug(
                    "[ResourceAgents] #%d id=%s name=%s updated_at=%s",
                    idx, rid, res.get("name"), res.get("updated_at")
                )
                try:
                    # Map Resource -> AgentSettings
                    settings = self._resource_to_agent_settings_v1(res, type_to_class)
                    logger.debug(
                        "[ResourceAgents] mapped -> name=%s type=%s class_path=%s servers=%d prompt_len=%d",
                        settings.name, settings.type, settings.class_path,
                        len(settings.mcp_servers or []),
                        len(settings.base_prompt or "") if settings.base_prompt else 0,
                    )

                    # Idempotency / replace-on-change
                    existing = self.agent_settings.get(settings.name)
                    if existing and not replace_on_change:
                        logger.debug("[ResourceAgents] '%s' exists; replace_on_change=False -> skip", settings.name)
                        continue

                    if existing and replace_on_change:
                        prev = (existing.settings or {}).get("_resource_updated_at")
                        now = res.get("updated_at")
                        if prev == now:
                            logger.debug("[ResourceAgents] '%s' unchanged (updated_at=%s) -> skip", settings.name, now)
                            continue
                        logger.info("[ResourceAgents] '%s' changed (prev=%s, now=%s) -> recreate", settings.name, prev, now)
                        self.unregister_agent(settings.name)

                    # Import class and instantiate
                    module_name, class_name = settings.class_path.rsplit(".", 1)
                    logger.debug(
                        "[ResourceAgents] importing class_path=%s (module=%s, class=%s)",
                        settings.class_path, module_name, class_name
                    )
                    try:
                        module = importlib.import_module(module_name)
                        cls = getattr(module, class_name)
                    except Exception:
                        logger.exception(f"[ResourceAgents] import failed for class_path={settings.class_path}")
                        # optional: try known fallbacks if you want
                        continue

                    if not issubclass(cls, AgentFlow):
                        logger.error(f"[ResourceAgents] class {cls} is not AgentFlow; skip name={settings.name}")
                        continue

                    instance = cls(agent_settings=settings)

                    # ⚠️ Critical: catch BaseException so GeneratorExit/anyio cancel scope doesn't kill lifespan
                    if iscoroutinefunction(getattr(instance, "async_init", None)):
                        try:
                            await instance.async_init()
                            logger.debug("[ResourceAgents] async_init OK for '%s'", settings.name)
                        except BaseException as be:  # <-- broader than Exception
                            logger.exception(
                                "[ResourceAgents] async_init failed hard for '%s' (suppressed to keep startup alive)",
                                settings.name
                            )
                            # skip registering this broken agent to keep the app healthy
                            continue

                    self.register_dynamic_agent(instance, settings)
                    logger.info("[ResourceAgents] registered '%s' (nickname=%s)", settings.name, settings.nickname)

                    if existing:
                        updated += 1
                    else:
                        added += 1

                except Exception:
                    logger.exception("Failed to load resource agent", extra={"resource_id": res.get("id")})

            if added or updated:
                self._inject_experts_into_leaders()
                logger.info(
                    "Resource agents loaded (v1). added=%d, updated=%d. Enabled=%s",
                    added, updated, ", ".join(sorted(self.get_enabled_agent_names()))
                )
            else:
                logger.info(
                    "Resource agents loaded (v1). nothing to add/update. Enabled=%s",
                    ", ".join(sorted(self.get_enabled_agent_names()))
                )
        except BaseException as be:
            # Final guard so FastAPI lifespan doesn't crash with "generator didn't yield"
            logger.exception("[ResourceAgents] loader aborted by fatal error (suppressed): %s", be)
            return

    def _resource_to_agent_settings_v1(
        self,
        res: Dict[str, Any],
        type_to_class: Dict[str, str],
    ) -> AgentSettings:
        """
        Minimal v1 mapping:
        - Parse YAML header from resource.content (front-matter before '---').
        - Map fields to AgentSettings.
        - Put only bookkeeping info in settings["_resource_updated_at"] (allowed).
        """
        rid = str(res.get("id"))
        content = (res.get("content") or "").strip()
        preview = (content[:160].replace("\n", "\\n") + ("…" if len(content) > 160 else ""))
        logger.debug("[ResourceAgents] map id=%s content_preview=%s", rid, preview)

        header, body = self._split_yaml_header(content)
        logger.debug("[ResourceAgents] header_keys=%s body_len=%d", list(header.keys()), len(body or ""))

        # name/description fallbacks
        name = header.get("name") or res.get("name") or f"agent:{rid}"
        description = header.get("description") or res.get("description") or name
        nickname = header.get("nickname") or None
        role = header.get("role") or "Dynamic Agent"
        icon = header.get("icon") or "Robot"
        labels = header.get("labels") or res.get("labels") or []
        rtype = (header.get("type") or "mcp").lower()

        class_path = header.get("class_path") or type_to_class.get(rtype)
        logger.debug("[ResourceAgents] rtype=%s class_path=%s", rtype, class_path)
        if not class_path:
            raise ValueError(f"No class_path mapping for type='{rtype}'.")

        mcp_servers = self._extract_mcp_servers_v1(header)
        logger.debug("[ResourceAgents] servers_count=%d", len(mcp_servers or []))

        # pick a default model from config (adapt to your config shape)
        model_cfg = getattr(self.config.ai, "default_model", None) or getattr(self.config.ai, "model", None)
        if not model_cfg:
            models = getattr(self.config.ai, "models", None)
            model_cfg = models[0] if models else None
        if not model_cfg:
            raise ValueError("No default model configuration available for dynamic resource agents.")
        logger.debug("[ResourceAgents] model_cfg=%s", getattr(model_cfg, "model_id", None) or type(model_cfg).__name__)

        # Only use fields that exist on AgentSettings
        settings = AgentSettings(
            type=rtype if rtype in ("mcp", "custom", "leader") else "custom",
            name=name,
            class_path=class_path,
            enabled=True,
            categories=list(labels),
            settings={"_resource_updated_at": res.get("updated_at")},  # v1 change tracking
            model=model_cfg,
            tag="resource-agent",
            mcp_servers=mcp_servers,
            max_steps=10,
            description=description,
            base_prompt=body or None,
            nickname=nickname,
            role=role,
            icon=icon,
        )
        logger.debug("[ResourceAgents] built AgentSettings name=%s", settings.name)
        return settings

    def _extract_mcp_servers_v1(self, header: Dict[str, Any]) -> List[MCPServerConfiguration]:
        """Normalize to a typed list of MCPServerConfiguration (not plain dicts)."""
        candidates = header.get("mcpServers") or header.get("mcp_servers") or header.get("servers") or []
        if not isinstance(candidates, list):
            candidates = [candidates]
        logger.debug("[ResourceAgents] servers candidates len=%d", len(candidates))

        out: List[MCPServerConfiguration] = []
        for i, s in enumerate(candidates):
            if not isinstance(s, dict):
                logger.debug("[ResourceAgents] skip server[%d]: not a dict", i)
                continue

            # Normalize transport to your supported literals
            transport = (s.get("transport") or "sse").lower()
            if transport in ("ws", "websocket"):
                transport = "websocket"
            elif transport in ("http2", "h2"):
                transport = "streamable_http"
            elif transport == "stdio":
                transport = "stdio"
            else:
                transport = "sse"

            args_val = s.get("args")
            if not isinstance(args_val, list):
                args_val = None

            env_val = s.get("env")
            if not isinstance(env_val, dict):
                env_val = None

            cfg = MCPServerConfiguration(
                name=str(s.get("name") or "MCP"),
                url=str(s.get("url") or s.get("baseUrl") or ""),
                transport=transport,                 # matches SUPPORTED_TRANSPORTS
                sse_read_timeout=int(s.get("timeout") or s.get("sse_read_timeout") or 600),
                command=s.get("command"),
                args=args_val,                       # List[str] | None
                env=env_val,                         # Dict[str, str] | None
            )
            logger.debug("[ResourceAgents] server[%d] name=%s url=%s transport=%s", i, cfg.name, cfg.url, cfg.transport)
            out.append(cfg)
        return out

    
    def _split_yaml_header(self, content: str) -> tuple[Dict[str, Any], str]:
        """Front-matter support: YAML header then '---' then body; else treat all as YAML or body."""
        if not content:
            logger.debug("[ResourceAgents] empty content")
            return {}, ""
        sep = "\n---\n"
        if sep in content:
            header_text, body = content.split(sep, 1)
            try:
                header = yaml.safe_load(header_text) or {}
                if not isinstance(header, dict):
                    header = {}
            except Exception as e:
                logger.debug("[ResourceAgents] YAML front-matter parse failed: %s", e)
                header = {}
            logger.debug("[ResourceAgents] split front-matter: header_len=%d body_len=%d", len(header_text), len(body))
            return header, body
        try:
            header = yaml.safe_load(content) or {}
            if isinstance(header, dict):
                logger.debug("[ResourceAgents] single-doc YAML header only (no body)")
                return header, ""
            logger.debug("[ResourceAgents] content is not YAML dict; using as body")
            return {}, content
        except Exception as e:
            logger.debug("[ResourceAgents] YAML parse failed; treat as body. err=%s", e)
            return {}, content


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

    async def _load_all_persisted_agents(self):
        """
        Loads all AgentSettings from persistent storage (e.g., DuckDB),
        dynamically imports their class, instantiates them, and (if needed) calls `async_init()`.

        On success, the agent is fully usable and added to the in-memory registry.
        """
        for agent_settings in self.store.load_all():
            if not agent_settings.class_path:
                logger.warning(
                    f"No class_path for agent '{agent_settings.name}' — skipping."
                )
                continue

            try:
                module_name, class_name = agent_settings.class_path.rsplit(".", 1)
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)

                if not issubclass(cls, (AgentFlow)):
                    logger.error(f"Class '{cls}' is not a supported Flow or AgentFlow.")
                    continue

                instance = cls(agent_settings=agent_settings)

                if iscoroutinefunction(getattr(instance, "async_init", None)):
                    await instance.async_init()

                self._register_loaded_agent(
                    agent_settings.name, instance, agent_settings
                )

                logger.info(
                    f"✅ Loaded expert agent '{agent_settings.name}' ({agent_settings.class_path})"
                )

            except Exception as e:
                logger.exception(
                    f"❌ Failed to load agent '{agent_settings.name}': {e}"
                )

    def _inject_experts_into_leaders(self):
        """
        After all agents are loaded and registered:
        - Inject each expert agent (AgentFlow) into each leader agent (Flow with type='leader')
        - Only injects if the leader supports `add_expert()`
        """
        for leader_name, leader_settings in self.agent_settings.items():
            if leader_settings.type != "leader":
                continue

            leader_instance = self.get_agent_instance(leader_name)
            if not isinstance(leader_instance, Leader):
                continue

            for expert_name, expert_settings in self.agent_settings.items():
                if expert_name == leader_name:
                    continue
                if not issubclass(self.agent_classes[expert_name], AgentFlow):
                    continue

                expert_instance = self.get_agent_instance(expert_name)
                compiled_graph = expert_instance.get_compiled_graph()

                leader_instance.add_expert(expert_name, expert_instance, compiled_graph)
                logger.info(
                    f"👥 Added expert '{expert_name}' to leader '{leader_name}'"
                )

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

    def unregister_agent(self, name: str):
        """
        Removes an agent from in-memory maps. Does not affect persisted storage.
        """
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

    def get_mcp_client(self, agent_name: str) -> MultiServerMCPClient:
        agent_settings = self.get_agent_settings(agent_name)
        import asyncio

        import nest_asyncio

        nest_asyncio.apply()

        client = MultiServerMCPClient()
        loop = asyncio.get_event_loop()

        async def connect_all():
            exceptions = []
            for server in agent_settings.mcp_servers:
                if server.transport not in SUPPORTED_TRANSPORTS:
                    raise UnsupportedTransportError(
                        f"Unsupported transport: {server.transport}"
                    )
                try:
                    await client.connect_to_server(
                        server_name=server.name,
                        url=server.url,
                        transport=server.transport,
                        command=server.command,
                        args=server.args,
                        env=server.env,
                        sse_read_timeout=server.sse_read_timeout,
                    )
                    logger.info(
                        f"✅ Connected to MCP server '{server.name}' at '{server.url}'"
                    )
                except Exception as eg:
                    logger.warning(
                        f"⚠️ Failed to connect to MCP server '{server.name}': {eg}"
                    )
                    exceptions.extend(getattr(eg, "exceptions", [eg]))
            if exceptions:
                raise ExceptionGroup("Some MCP connections failed", exceptions)

        @retry(wait=wait_fixed(2), stop=stop_after_delay(20))
        async def retry_connect_all():
            await connect_all()

        try:
            loop.run_until_complete(retry_connect_all())
        except RetryError as re:
            logger.error(
                f"❌ MCP client for agent '{agent_name}' failed to connect after retries."
            )
            logger.debug(re)
        except Exception:
            logger.exception(
                f"❌ MCP client for agent '{agent_name}' raised an unexpected error."
            )

        return client

    async def _retry_failed_agents_loop(self):
        logger.debug("🔄 Agent retry loop started.")
        while True:
            await asyncio.sleep(10)
            if not self.failed_agents:
                logger.debug("🔄 Agent retry all is all right.")
                continue

            try:
                logger.info("🔁 Retrying failed agents...")
                to_remove = []
                for name, agent_cfg in list(self.failed_agents.items()):
                    success = await self._register_static_agent(agent_cfg)
                    if success:
                        logger.info(f"✅ Recovered agent '{name}' on retry.")
                        to_remove.append(name)
                    else:
                        logger.debug(f"🔁 Agent '{name}' still failing.")
                for name in to_remove:
                    del self.failed_agents[name]
            except Exception:
                logger.exception(
                    "🔥 Unexpected error in retry loop — will continue anyway"
                )
