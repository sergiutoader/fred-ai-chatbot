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
AgentLoader — creates AgentFlow instances from multiple sources
(static config, persisted store, and Knowledge-Flow resources) and runs
their bounded async setup (`async_init()`).

Design contract:
- Loader is **pure creation** + **bounded init** only.
- Loader never starts long-lived work (streams/pollers) — that’s Supervisor’s job.
- Loader never mutates the registry — AgentManager (or a Registry) decides
  how to register/unregister/replace after instances are returned.

Public API:
- load_static() -> (instances, failed_map)
- load_persisted() -> instances
- load_resource_agents(...) -> (instances_to_add_or_update, names_to_replace)
"""

from __future__ import annotations

import importlib
import logging
from inspect import iscoroutinefunction
from typing import Any, Dict, List, Mapping, Optional, Tuple, Type

import requests
import yaml
from anyio import to_thread
from app.common.kf_base_client import KfServiceUnavailable
from app.common.kf_resource_client import KfResourceClient
from app.common.structures import (
    AgentSettings,
    Configuration,
    MCPServerConfiguration,
)
from app.core.agents.flow import AgentFlow
from app.core.agents.store.base_agent_store import BaseAgentStore

logger = logging.getLogger(__name__)

SUPPORTED_TRANSPORTS = ["sse", "stdio", "streamable_http", "websocket"]


class AgentLoader:
    """
    Factory for AgentFlow instances with a bounded async initialization step.

    Rationale:
    - Keeps `AgentManager` small and focused on orchestration.
    - Makes testing easier: you can unit-test mapping and init paths separately.
    """

    def __init__(self, config: Configuration, store: BaseAgentStore):
        self.config = config
        self.store = store

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    async def load_static(self) -> Tuple[List[AgentFlow], Dict[str, AgentSettings]]:
        """
        Build agents declared in configuration (enabled only), run `async_init()`,
        and return `(instances, failed_map)`. `failed_map` contains AgentSettings
        for static agents that failed to import/instantiate/init (so a retry loop
        can attempt later).
        """
        instances: List[AgentFlow] = []
        failed: Dict[str, AgentSettings] = {}

        for agent_cfg in self.config.ai.agents:
            if not agent_cfg.enabled:
                continue

            try:
                cls = self._import_agent_class(agent_cfg.class_path)
                if not issubclass(cls, AgentFlow):
                    logger.error(
                        "Class '%s' is not AgentFlow for '%s'",
                        agent_cfg.class_path,
                        agent_cfg.name,
                    )
                    failed[agent_cfg.name] = agent_cfg
                    continue

                inst: AgentFlow = cls(agent_settings=agent_cfg)

                if iscoroutinefunction(getattr(inst, "async_init", None)):
                    # Catch BaseException so GeneratorExit doesn’t take down the lifespan.
                    try:
                        await inst.async_init()
                    except BaseException as be:
                        logger.exception(
                            "Static async_init failed for '%s' (suppressed): %s",
                            agent_cfg.name,
                            be,
                        )
                        failed[agent_cfg.name] = agent_cfg
                        continue

                instances.append(inst)
                logger.info("✅ Static agent ready: %s", agent_cfg.name)

            except Exception as e:
                logger.exception(
                    "❌ Failed to construct static agent '%s': %s", agent_cfg.name, e
                )
                failed[agent_cfg.name] = agent_cfg

        return instances, failed

    async def load_persisted(self) -> List[AgentFlow]:
        """
        Build agents from persistent storage (e.g., DuckDB), run `async_init()`,
        and return ready instances. Agents with missing/invalid class_path are skipped.
        """
        out: List[AgentFlow] = []

        for agent_settings in self.store.load_all():
            if not agent_settings.class_path:
                logger.warning(
                    "No class_path for agent '%s' — skipping.", agent_settings.name
                )
                continue

            try:
                cls = self._import_agent_class(agent_settings.class_path)
                if not issubclass(cls, AgentFlow):
                    logger.error(
                        "Class '%s' is not AgentFlow for '%s'",
                        agent_settings.class_path,
                        agent_settings.name,
                    )
                    continue

                inst: AgentFlow = cls(agent_settings=agent_settings)

                if iscoroutinefunction(getattr(inst, "async_init", None)):
                    try:
                        await inst.async_init()
                    except BaseException as be:
                        logger.exception(
                            "Persisted async_init failed for '%s' (suppressed): %s",
                            agent_settings.name,
                            be,
                        )
                        continue

                out.append(inst)
                logger.info(
                    "✅ Persisted agent loaded: %s (%s)",
                    agent_settings.name,
                    agent_settings.class_path,
                )

            except Exception as e:
                logger.exception(
                    "❌ Failed to load persisted agent '%s': %s",
                    agent_settings.name,
                    e,
                )

        return out

    async def load_resource_agents(
        self,
        base_url: str,
        *,
        type_to_class: Dict[str, str],
        replace_on_change: bool = True,
        existing_settings: Optional[Mapping[str, AgentSettings]] = None,
    ) -> Tuple[List[AgentFlow], List[str]]:
        """
        Fetch resource-backed agents from Knowledge-Flow, map them to AgentSettings,
        construct + `async_init()` instances, and decide which existing names should
        be replaced (based on updated_at).

        Returns:
            (instances_to_add_or_update, names_to_replace)

        Notes:
        - This function does NOT unregister/close current agents. The caller decides
          how to handle `names_to_replace` (typically: close+unregister, then register new).
        - If `replace_on_change=False`, any existing name is skipped regardless of updated_at.
        - If unchanged (same updated_at), we skip it silently.
        """
        if not type_to_class:
            logger.error(
                "[ResourceAgents] Missing type_to_class mapping "
                "(e.g., {'mcp': 'app.core.agents.mcp_agent.MCPAgent'})"
            )
            return [], []

        rc = KfResourceClient()

        try:
            resources = await to_thread.run_sync(rc.list_resources, "agent")
        except KfServiceUnavailable:
            logger.info(
                "[ResourceAgents] Knowledge-Flow unreachable; skipping dynamic agents."
            )
            return [], []
        except requests.HTTPError as e:
            logger.info(
                "[ResourceAgents] Knowledge-Flow responded %s; skipping dynamic agents.",
                getattr(e.response, "status_code", "HTTPError"),
            )
            return [], []

        if not resources:
            logger.warning(
                "[ResourceAgents] no resources returned; check base_url/path/auth"
            )
            return [], []

        # Decide replacements vs creations
        existing_settings = existing_settings or {}
        to_replace: List[str] = []
        to_create: List[AgentSettings] = []

        for idx, res in enumerate(resources):
            rid = res.get("id")
            logger.debug(
                "[ResourceAgents] #%d id=%s name=%s updated_at=%s",
                idx,
                rid,
                res.get("name"),
                res.get("updated_at"),
            )

            try:
                mapped = self._resource_to_agent_settings_v1(res, type_to_class)
            except Exception:
                logger.exception(
                    "[ResourceAgents] mapping failed for id=%s (skipped)", rid
                )
                continue

            existing = existing_settings.get(mapped.name)
            if existing is None:
                to_create.append(mapped)
                continue

            if not replace_on_change:
                logger.debug(
                    "[ResourceAgents] '%s' exists; replace_on_change=False -> skip",
                    mapped.name,
                )
                continue

            prev = (existing.settings or {}).get("_resource_updated_at")
            now = (mapped.settings or {}).get("_resource_updated_at")
            if prev == now:
                logger.debug(
                    "[ResourceAgents] '%s' unchanged (updated_at=%s) -> skip",
                    mapped.name,
                    now,
                )
                continue

            logger.info(
                "[ResourceAgents] '%s' changed (prev=%s, now=%s) -> will replace",
                mapped.name,
                prev,
                now,
            )
            to_replace.append(mapped.name)
            to_create.append(mapped)  # create new instance after caller closes old

        # Instantiate + async_init()
        instances: List[AgentFlow] = []
        for settings in to_create:
            try:
                cls = self._import_agent_class(settings.class_path)
                if not issubclass(cls, AgentFlow):
                    logger.error(
                        "[ResourceAgents] class %s is not AgentFlow; skip name=%s",
                        cls,
                        settings.name,
                    )
                    continue

                inst: AgentFlow = cls(agent_settings=settings)
                if iscoroutinefunction(getattr(inst, "async_init", None)):
                    try:
                        await inst.async_init()
                        logger.debug(
                            "[ResourceAgents] async_init OK for '%s'",
                            settings.name,
                        )
                    except BaseException:
                        logger.exception(
                            "[ResourceAgents] async_init failed for '%s' (suppressed)",
                            settings.name,
                        )
                        continue

                instances.append(inst)

            except Exception:
                logger.exception(
                    "[ResourceAgents] failed to create '%s'", settings.name
                )

        return instances, to_replace

    # ---------------------------------------------------------------------
    # Private helpers (mapping / import)
    # ---------------------------------------------------------------------

    def _import_agent_class(self, class_path: str) -> Type[AgentFlow]:
        module_name, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        return getattr(module, class_name)

    def _resource_to_agent_settings_v1(
        self,
        res: Dict[str, Any],
        type_to_class: Dict[str, str],
    ) -> AgentSettings:
        """
        Map a Knowledge-Flow resource to AgentSettings (v1):
        - Parse YAML front-matter from resource.content (header body split by `---`).
        - Choose class_path using header or the provided `type_to_class` mapping.
        - Normalize MCP server configs to typed MCPServerConfiguration instances.
        - Track change detection by storing `_resource_updated_at` in settings.settings.
        """
        rid = str(res.get("id"))
        content = (res.get("content") or "").strip()
        header, body = self._split_yaml_header(content)

        # name/description fallbacks
        name = header.get("name") or res.get("name") or f"agent:{rid}"
        description = header.get("description") or res.get("description") or name
        nickname = header.get("nickname") or None
        role = header.get("role") or "Dynamic Agent"
        icon = header.get("icon") or "Robot"
        labels = header.get("labels") or res.get("labels") or []
        rtype = (header.get("type") or "mcp").lower()

        class_path = header.get("class_path") or type_to_class.get(rtype)
        if not class_path:
            raise ValueError(f"No class_path mapping for type='{rtype}'.")

        mcp_servers = self._extract_mcp_servers_v1(header)

        # Pick a default model from config (adapt if your config differs)
        model_cfg = getattr(self.config.ai, "default_model", None) or getattr(
            self.config.ai, "model", None
        )
        if not model_cfg:
            models = getattr(self.config.ai, "models", None)
            model_cfg = models[0] if models else None
        if not model_cfg:
            raise ValueError(
                "No default model configuration available for dynamic resource agents."
            )

        settings = AgentSettings(
            type=rtype if rtype in ("mcp", "custom", "leader") else "custom",
            name=name,
            class_path=class_path,
            enabled=True,
            categories=list(labels),
            settings={"_resource_updated_at": res.get("updated_at")},
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
        return settings

    def _extract_mcp_servers_v1(
        self, header: Dict[str, Any]
    ) -> List[MCPServerConfiguration]:
        """
        Normalize various header shapes into a list of MCPServerConfiguration.
        Accepts keys: mcpServers | mcp_servers | servers
        """
        candidates = (
            header.get("mcpServers")
            or header.get("mcp_servers")
            or header.get("servers")
            or []
        )
        if not isinstance(candidates, list):
            candidates = [candidates]

        out: List[MCPServerConfiguration] = []
        for s in candidates:
            if not isinstance(s, dict):
                continue

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

            out.append(
                MCPServerConfiguration(
                    name=str(s.get("name") or "MCP"),
                    url=str(s.get("url") or s.get("baseUrl") or ""),
                    transport=transport,
                    sse_read_timeout=int(
                        s.get("timeout") or s.get("sse_read_timeout") or 600
                    ),
                    command=s.get("command"),
                    args=args_val,
                    env=env_val,
                )
            )
        return out

    def _split_yaml_header(self, content: str) -> Tuple[Dict[str, Any], str]:
        """
        Front-matter support:
        - YAML header then '---' then body; else treat as YAML dict or plain body.
        Returns (header_dict, body_text).
        """
        if not content:
            return {}, ""
        sep = "\n---\n"
        if sep in content:
            header_text, body = content.split(sep, 1)
            try:
                header = yaml.safe_load(header_text) or {}
                if not isinstance(header, dict):
                    header = {}
            except Exception:
                header = {}
            return header, body

        try:
            header = yaml.safe_load(content) or {}
            if isinstance(header, dict):
                return header, ""
            return {}, content
        except Exception:
            return {}, content
