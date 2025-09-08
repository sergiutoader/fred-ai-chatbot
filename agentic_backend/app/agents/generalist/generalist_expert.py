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

# In app/core/agents/GeneralistExpert.py

import logging
from datetime import datetime
from typing import List

from langgraph.graph import START, END, MessagesState, StateGraph
from langchain_core.messages import BaseMessage

from app.common.structures import AgentSettings
from app.core.model.model_factory import get_model
from app.core.agents.flow import AgentFlow

logger = logging.getLogger(__name__)

class GeneralistExpert(AgentFlow):

    def __init__(self, agent_settings: AgentSettings):
        super().__init__(agent_settings=agent_settings)

    async def async_init(self):
        # The base class handles fetching the binding and the base prompt.
        await self.load_agent_configuration(self._generate_fallback_prompt)
        self.model = get_model(self.agent_settings.model)
        self._graph = self._build_graph()

    def _generate_fallback_prompt(self) -> str:
        # A hardcoded fallback, just in case the API is down or the binding is missing.
        today = datetime.now().strftime("%Y-%m-%d")
        return (
            f"You are a friendly generalist expert. The current date is {today}."
        )

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(MessagesState)
        builder.add_node("expert", self.reasoner)
        builder.add_edge(START, "expert")
        builder.add_edge("expert", END)
        return builder

    async def reasoner(self, state: MessagesState):
        # Call the new, clean API to get the full list of messages.
        # We pass in the node's key ('expert' in this case).
        messages: List[BaseMessage] = await self.compose_messages(
            node_key="expert",
            messages=state["messages"]
        )
        
        assert self.model is not None
        response = await self.model.ainvoke(messages)
        return {"messages": [response]}