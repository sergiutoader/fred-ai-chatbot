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
# app/core/agents/agent_supervisor.py

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from inspect import iscoroutinefunction
from typing import Awaitable, Callable, Iterable

import anyio
from anyio.abc import TaskGroup

from app.core.agents.flow import AgentFlow
from app.agents.leader.leader import Leader

logger = logging.getLogger(__name__)


class AgentSupervisor:
    """
    Owns long-lived agent work and cleanup.

    Responsibilities:
    - Start agents' `async_start(tg)` under the application's TaskGroup.
    - Close agents via `aclose()` from the SAME task on shutdown.
    - Run a retry loop (provided a retry coroutine).
    - Inject experts into leaders after (re)loads.
    """

    def __init__(self) -> None:
        self._retry_scope: anyio.CancelScope | None = None
        self._retry_task: asyncio.Task | None = None

    # -----------------------
    # Lifecycle orchestration
    # -----------------------

    async def start_agents(self, tg: TaskGroup, agents: Iterable[AgentFlow]) -> None:
        """
        Start long-lived work for each agent (if they implement async_start).
        """
        for agent in agents:
            start = getattr(agent, "async_start", None)
            if iscoroutinefunction(start):
                try:
                    await start(tg=tg)
                except Exception:
                    logger.exception(
                        "Agent %s async_start failed; agent remains registered but inactive.",
                        getattr(agent, "name", "<unnamed>"),
                    )

    async def close_agents(self, agents: Iterable[AgentFlow]) -> None:
        """
        Close agents (if they implement aclose). Idempotent, best effort.
        """
        for agent in agents:
            close = getattr(agent, "aclose", None)
            if iscoroutinefunction(close):
                try:
                    await close()
                except Exception:
                    logger.debug(
                        "Agent %s aclose() failed (ignored).",
                        getattr(agent, "name", "<unnamed>"),
                    )

    # ------------
    # Retry engine
    # ------------

    def start_retry_loop(
        self, tg: TaskGroup, retry_fn: Callable[[], Awaitable[None]]
    ) -> None:
        """
        Start a cooperative retry loop under the app TaskGroup.

        `retry_fn` encapsulates your manager's "retry failed statics" logic.
        """

        if self._retry_scope or (self._retry_task and not self._retry_task.done()):
            return  # already running

        self._retry_scope = anyio.CancelScope()

        async def _run():
            scope = self._retry_scope
            if scope is None:
                return
            with scope:
                while True:
                    await anyio.sleep(10)
                    try:
                        await retry_fn()
                    except Exception:
                        logger.exception("Retry loop threw; continuing.")

        tg.start_soon(_run)

    def stop_retry_loop(self) -> None:
        if self._retry_scope is not None:
            self._retry_scope.cancel()
            self._retry_scope = None
        if self._retry_task is not None and not self._retry_task.done():
            self._retry_task.cancel()
            self._retry_task = None

    # --------------------------
    # Leader–expert integration
    # --------------------------

    def inject_leaders(
        self,
        *,
        agents_by_name: Mapping[str, AgentFlow],
        settings_by_name: Mapping[str, object],
        classes_by_name: Mapping[str, type],
    ) -> None:
        """
        After (re)load: inject each expert into each leader.

        Contract:
        - Leaders are instances of `Leader`.
        - Experts are subclasses of `AgentFlow`.
        """
        for leader_name, leader_settings in settings_by_name.items():
            # leader_settings must have `type` attribute or key == "leader"
            leader_type = getattr(leader_settings, "type", None)
            if leader_type != "leader":
                continue

            leader_instance = agents_by_name.get(leader_name)
            if not isinstance(leader_instance, Leader):
                continue

            for expert_name, expert_cls in classes_by_name.items():
                if expert_name == leader_name:
                    continue
                if not issubclass(expert_cls, AgentFlow):
                    continue

                expert_instance = agents_by_name.get(expert_name)
                if not isinstance(expert_instance, AgentFlow):
                    continue

                compiled = expert_instance.get_compiled_graph()
                leader_instance.add_expert(expert_name, expert_instance, compiled)
                logger.info(
                    "👥 Added expert '%s' to leader '%s'", expert_name, leader_name
                )
