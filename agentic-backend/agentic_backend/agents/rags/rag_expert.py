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


import logging
from typing import List

from fred_core import VectorSearchHit
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from agentic_backend.application_context import get_default_chat_model
from agentic_backend.common.kf_vectorsearch_client import VectorSearchClient
from agentic_backend.common.rags_utils import (
    attach_sources_to_llm_response,
    ensure_ranks,
    format_sources_for_prompt,
    sort_hits,
)
from agentic_backend.common.structures import AgentChatOptions
from agentic_backend.core.agents.agent_flow import AgentFlow
from agentic_backend.core.agents.agent_spec import AgentTuning, FieldSpec, UIHints
from agentic_backend.core.agents.runtime_context import (
    RuntimeContext,
    get_document_library_tags_ids,
    get_search_policy,
)
from agentic_backend.core.runtime_source import expose_runtime_source

logger = logging.getLogger(__name__)

# -----------------------------
# Spec-only tuning (class-level)
# -----------------------------
# Dev note:
# - These are *UI schema fields* (spec). Live values come from AgentSettings.tuning
#   and are applied by AgentFlow at runtime.
RAG_TUNING = AgentTuning(
    role="Document retrieval and QA expert",
    description="An expert in retrieving and processing documents using retrieval-augmented generation techniques. SmurfIA can help with tasks that involve understanding and utilizing large document collections.",
    tags=["document"],
    fields=[
        FieldSpec(
            key="prompts.system",
            type="prompt",
            title="RAG System Prompt",
            description=(
                "Sets the assistant policy for evidence-based answers and citation style."
            ),
            required=True,
            default=(
                "You answer strictly based on the retrieved document chunks.\n"
                "Always cite claims using bracketed numeric markers like [1], [2], matching the provided sources list.\n"
                "Be concise and factual. If evidence is weak or missing, say so."
            ),
            ui=UIHints(group="Prompts", multiline=True, markdown=True),
        ),
        FieldSpec(
            key="rag.top_k",
            type="integer",
            title="Top-K Documents",
            description="How many chunks to retrieve per question.",
            required=False,
            default=3,
            ui=UIHints(group="Retrieval"),
        ),
        FieldSpec(
            key="prompts.include_chat_context",
            type="boolean",
            title="Append Chat Context to System Prompt",
            description="If true, append the runtime chat context text after the system prompt.",
            required=False,
            default=False,
            ui=UIHints(group="Prompts"),
        ),
    ],
)


@expose_runtime_source("agent.Rico")
class Rico(AgentFlow):
    """
    Retrieval-Augmented Generation expert with lightweight per-session onboarding memory
    (name, project, role). Retrieval runs only after onboarding is complete.
    """

    # -----------------------------
    # Imports scoped inside the class (keeps this drop-in self-contained)
    # -----------------------------
    from dataclasses import dataclass
    from typing import Optional
    import re as _re
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    except Exception:  # fallback for older setups
        from langchain.schema import AIMessage, HumanMessage, SystemMessage

    # -----------------------------
    # Lightweight onboarding memory
    # -----------------------------
    @dataclass
    class _OnboardingState:
        name: str | None = None
        project: str | None = None
        role: str | None = None
        ack_sent: bool = False  # one-time "ready" acknowledgement

        @property
        def is_complete(self) -> bool:
            return bool(self.name and self.project and self.role)

    class _OnboardingMemoryStore:
        """Very small in-process store keyed by a session/user id."""
        def __init__(self):
            self._store: dict[str, "Rico._OnboardingState"] = {}

        def get(self, key: str) -> "Rico._OnboardingState":
            return self._store.setdefault(key, Rico._OnboardingState())

        def update(self, key: str, overwrite: bool = False, **kwargs) -> "Rico._OnboardingState":
            """
            By default, only fills missing values (no overwrite).
            Set overwrite=True to force replacement (e.g., for ack flag).
            """
            st = self.get(key)
            for k, v in kwargs.items():
                if v is None or v == "":
                    continue
                if overwrite or getattr(st, k, None) in (None, ""):
                    setattr(st, k, v)
            self._store[key] = st
            return st
        
    # -----------------------------

    tuning = RAG_TUNING  # UI schema only; live values are in AgentSettings.tuning
    default_chat_options = AgentChatOptions(
        search_policy_selection=True,
        libraries_selection=True,
    )

    async def async_init(self, runtime_context: RuntimeContext):
        """Bind the model, create the vector search client, and build the graph."""
        self.model = get_default_chat_model()
        self.search_client = VectorSearchClient(agent=self)
        self._onboard_store = self._OnboardingMemoryStore()
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(MessagesState)
        builder.add_node("reasoner", self._run_reasoning_step)
        builder.add_edge(START, "reasoner")
        builder.add_edge("reasoner", END)
        return builder

    # -----------------------------
    # Small helpers (local policy)
    # -----------------------------
    def _system_prompt(self) -> str:
        sys_tpl = self.get_tuned_text("prompts.system")
        if not sys_tpl:
            logger.warning("SmurfIA: no tuned system prompt found, using fallback.")
            raise RuntimeError("SmurfIA: no tuned system prompt found.")
        return self.render(sys_tpl)  # token-safe rendering (e.g. {today})

    # -----------------------------
    # Onboarding helpers
    # -----------------------------
    def _session_key(self) -> str:
        rc = self.get_runtime_context()
        return (
            getattr(rc, "session_id", None)
            or getattr(rc, "user_id", None)
            or getattr(rc, "conversation_id", None)
            or "global"
        )

    def _extract_onboarding_updates(
        self,
        text: str,
        current: Optional["_OnboardingState"] = None,
    ) -> dict:
        """
        Deterministic extractors for name/project/role from free text.
        Conservative name fallback to avoid capturing sentences like
        'I am working on Amadeus'.

        Normalizes project values by removing leading articles (the/a/an)
        and trailing 'project' so prompts don't duplicate words like
        'the the poker project project'.
        """
        t = (text or "").strip()
        updates: dict[str, str] = {}

        # helper: normalize project string
        def _normalize_project(p: str) -> str:
            if not p:
                return p
            p = p.strip()
            # remove leading article
            p = self._re.sub(r"^\s*(?:the|a|an)\s+", "", p, flags=self._re.I)
            # remove trailing word 'project' (and variations like 'project.')
            p = self._re.sub(r"\s*\bproject\b[\.\s]*$", "", p, flags=self._re.I)
            return p.strip()

        # --- explicit name ---
        m = self._re.search(r"\b(?:my\s+name\s+is|name\s*[:=])\s*([A-Z][\w\-\.' ]+)", t, self._re.I)
        if m:
            updates["name"] = m.group(1).strip()

        # --- explicit project ---
        m = self._re.search(r"\b(?:project\s*[:=]\s*|work(?:ing)?\s+on\s+)([A-Z0-9][\w\-\.' ]+)", t, self._re.I)
        if m:
            raw_proj = m.group(1).strip()
            updates["project"] = _normalize_project(raw_proj)

        # --- explicit or natural role phrasing ---
        m = self._re.search(
            r"\b(?:my\s+role\s+is|role\s*[:=]|i\s+am\s+a?n?|i\s+work\s+as\s+a?n?)\s+([A-Za-z][\w\-\.' /]+)",
            t,
            self._re.I,
        )
        if m:
            updates["role"] = m.group(1).strip().capitalize()

        # --- conservative name fallback ---
        if (
            (current is None or not current.name)
            and "name" not in updates
            and "project" not in updates
            and "role" not in updates
        ):
            looks_like_name = self._re.fullmatch(r"[A-Z][a-z]+(?:[ \-'][A-Z][a-z]+){0,2}", t)
            mentions_work = self._re.search(r"\b(work|working|project|role)\b", t, self._re.I)
            if looks_like_name and not mentions_work:
                updates["name"] = t

        # final safety: if project was captured but is empty after normalization, remove it
        if "project" in updates and not updates["project"]:
            updates.pop("project")

        return updates


    def _next_onboarding_prompt(self, st: _OnboardingState) -> str:
        if not st.name:
            return "Hello! Let's get you set up. Could you please tell me your full name?"
        if not st.project:
            return f"Thanks, {st.name}. What project are you working on?"
        if not st.role:
            return f"Got it. What's your role on the {st.project} project?"
        return ""

    def _ack_ready(self, st: _OnboardingState) -> str:
        return f"Perfect — I'm all set, {st.name}! What can I help you with today?"

    # -----------------------------
    # Node: reasoner
    # -----------------------------
    async def _run_reasoning_step(self, state: MessagesState):
        if self.model is None:
            raise RuntimeError("Model is not initialized. Did you forget to call async_init()?")

        last = state["messages"][-1]
        if not isinstance(last.content, str):
            raise TypeError(f"Expected string content for the last message, got: {type(last.content).__name__}")
        question = last.content.strip()

        # ----- Onboarding memory gate -----
        skey = self._session_key()
        st = self._onboard_store.get(skey)

        # self._chat_history.add_user(skey, question) # CHAT HISTORY

        # Try to capture any onboarding info from this turn (no overwrite)
        extracted = self._extract_onboarding_updates(question, st)
        if extracted:
            st = self._onboard_store.update(skey, overwrite=False, **extracted)

        # # Store user message in chat history
        # self._chat_memory.add_message(skey, "user", question)

        # If onboarding incomplete, ask only for the next missing detail
        if not st.is_complete:
            prompt = self._next_onboarding_prompt(st)
            return {"messages": [self.AIMessage(content=prompt)]}

        # One-time acknowledgement
        ack_text = ""  # define upfront
        if not st.ack_sent:
            ack_text = self._ack_ready(st)
            self._onboard_store.update(skey, overwrite=True, ack_sent=True)
            # Send the acknowledgement and stop here — wait for the next user query
            return {"messages": [self.AIMessage(content=ack_text)]}


        # ----- RAG flow -----
        try:
            # 1) Build retrieval scope from runtime context
            doc_tag_ids = get_document_library_tags_ids(self.get_runtime_context())
            search_policy = get_search_policy(self.get_runtime_context())
            top_k = self.get_tuned_int("rag.top_k", default=3)

            # 2) Vector search
            logger.info(
                f"SmurfIA RAG Debug | question={question!r} | doc_tag_ids={doc_tag_ids} | "
                f"search_policy={search_policy} | top_k={top_k}"
            )

            if not doc_tag_ids:
                logger.warning("SmurfIA: No document libraries selected, defaulting to all.")
                doc_tag_ids = None

            hits: List[VectorSearchHit] = self.search_client.search(
                question=question,
                top_k=top_k,
                document_library_tags_ids=doc_tag_ids,
                search_policy=search_policy,
            )

            logger.debug(f"SmurfIA: vector search returned {len(hits)} hits")
            if not hits:
                warn = "I couldn't find any relevant documents. Try rephrasing or expanding your query?"
                msg = warn if not ack_text else f"{ack_text}\n\n{warn}"
                messages = self.with_chat_context_text([self.HumanMessage(content=msg)])
                return {"messages": [await self.model.ainvoke(messages)]}

            # 3) Deterministic ordering + fill ranks
            hits = sort_hits(hits)
            ensure_ranks(hits)

            # 4) Build messages explicitly (no magic)
            sys_msg = self.SystemMessage(content=self._system_prompt())
            sources_block = format_sources_for_prompt(hits, snippet_chars=500)

            preface = (ack_text + "\n\n") if ack_text else ""
            human_msg = self.HumanMessage(
                content=(
                    f"{preface}"
                    f"Context:\nName: {st.name}\nProject: {st.project}\nRole: {st.role}\n\n"
                    "When name, project, or role are asked, answer the question but DO NOT precise the source documents.\n\n"
                    "Use the context above and ONLY the sources below to answer the question. "
                    "If sources disagree or are insufficient, say so briefly.\n\n"
                    f"Question:\n{question}\n\n"
                    f"Sources:\n{sources_block}\n"
                )
            )

            # 5) Ask the model
            messages = [sys_msg, human_msg]
            messages = self.with_chat_context_text(messages)
            answer = await self.model.ainvoke(messages)

            # 6) Attach rich sources metadata for the UI
            attach_sources_to_llm_response(answer, hits)

            return {"messages": [answer]}

        except Exception:
            logger.exception("SmurfIA: error in reasoning step.")
            return {"messages": [self.AIMessage(content="Sorry, something went wrong while searching documents. Please try again.")]}
