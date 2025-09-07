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
Pydantic-based default catalog for the fred-core library.

Why this file exists
--------------------
- Ship a coherent set of defaults (prompts, templates, policies, tool-instructions)
  and a clear *binding* of those resources to agents and nodes.
- Let Knowledge-Flow seed these into runtime stores *idempotently* (create if missing).
- Keep agent code simple: each node resolves its prompt by stable id (library + id).

Key principles
--------------
- Single library tag: "fred-core" (overridable by ops if needed).
- Small set of *intents* to keep things discoverable: 
  agent.system, node.system/*, policy.*, template.*, tool.instructions/*.
- Minimal node overrides (only where specialization matters); everything else inherits
  the agent.system prompt + global policies.

How to use
----------
- Knowledge-Flow (or a bootstrap script) should:
  1) create DEFAULT_CATALOG.library_tag if absent
  2) ensure each item in DEFAULT_CATALOG.items exists (create if not)
  3) ensure each binding in DEFAULT_CATALOG.agents exists in the Agent Store
- Agents then read bindings from the Agent Store; if unavailable, they may fall back
  to these defaults by id (agent code safety net).
"""

from __future__ import annotations

from typing import List, Optional, Dict, Literal
from pydantic import BaseModel, Field
import hashlib
import json
from datetime import datetime


# ---------- Data models (small and explicit) ----------

Kind = Literal["prompt", "template", "policy", "tool_instruction"]


class ResourceItem(BaseModel):
    """
    A single library resource: prompt, template, policy, or tool instruction.

    - id: stable, path-like (e.g., "node.system/grade_documents.permissive")
    - kind: one of prompt|template|policy|tool_instruction
    - intent: broad grouping used by the UI (e.g., "node.system", "policy.citations")
    - node_key: optional; set for node.system prompts to indicate which node they target
    - version: semver-ish string; bump when content changes in a breaking way
    - body: the actual instruction text or template
    - metadata: free-form; the seeder can persist it alongside content
    """
    name: str
    kind: Kind
    intent: str
    title: str
    description: str
    body: str
    version: str = "v1"
    node_key: Optional[str] = None
    metadata: Dict[str, str] = Field(default_factory=dict)


class AgentNodeOverride(BaseModel):
    """
    Associates a node (by node_key) with a specific prompt/template/policies.

    - prompt_id: node-specific system prompt (optional; inherit agent.system if omitted)
    - policies: list of policy ids to compose additively for this node
    - template_id: optional output template id (e.g., for generation)
    """
    node_key: str
    prompt_id: Optional[str] = None
    policies: List[str] = Field(default_factory=list)
    template_id: Optional[str] = None


class AgentBinding(BaseModel):
    """
    Declarative binding between an agent and the resources it should use by default.

    - key: stable backend key for the agent (not necessarily the class name)
    - display_name: UI label (kept here for convenience)
    - system_prompt_id: agent-level "soul" prompt id
    - node_overrides: targeted specializations for specific nodes
    """
    name: str
    display_name: str
    system_prompt_id: str
    node_overrides: List[AgentNodeOverride] = Field(default_factory=list)
    # Optional: default policies applied to *every* node; usually empty to avoid duplication
    default_policies: List[str] = Field(default_factory=list)


class Catalog(BaseModel):
    """
    The whole shipped catalog for a library: items + default agent bindings.
    """
    version: int = 1
    library_tag: str = "fred-core"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    items: List[ResourceItem] = Field(default_factory=list)
    agents: List[AgentBinding] = Field(default_factory=list)
    digest: Optional[str] = None

    def compute_digest(self) -> str:
        """
        Deterministic hash of (version, library, items, agents) for drift detection.
        """
        payload = {
            "version": self.version,
            "library_tag": self.library_tag,
            "items": [i.model_dump() for i in self.items],
            "agents": [a.model_dump() for a in self.agents],
        }
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()


# ---------- Helper constants (ids used below) ----------

# Policies
POLICY_JSON_STRICT = "policy.json/strict"
POLICY_STYLE_CONCISE = "policy.style/concise"
POLICY_CITATIONS_MD = "policy.citations/markdown"

# Templates
TEMPLATE_ANSWER_CITED_V1 = "template.answer/cited_v1"

# Tool instructions
TOOL_INSTR_VECTOR_SEARCH = "tool.instructions/vector_search"
TOOL_INSTR_TABULAR = "tool.instructions/tabular_sql"
TOOL_INSTR_SUPERVISION = "tool.instructions/supervision_metrics"
TOOL_INSTR_RESOURCES_MCP = "tool.instructions/resources_mcp"

# Agents (keys)
AGENT_RAG = "advanced_rag"           # Remulus
AGENT_TABULAR = "tabular_expert"     # (Tessa-like)
AGENT_SUPERVISION = "supervision"    # (Sentinel/Supervisor)
AGENT_CONTENT_ADMIN = "content_admin"  # Brontë

# Agent-level system prompts
AGENT_SYS_RAG = "agent.system/advanced_rag"
AGENT_SYS_TABULAR = "agent.system/tabular"
AGENT_SYS_SUPERVISION = "agent.system/supervision"
AGENT_SYS_CONTENT_ADMIN = "agent.system/content_admin"


# ---------- Items: prompts, policies, templates, tool instructions ----------

_ITEMS: List[ResourceItem] = [

    # ===== Policies (reused across nodes/agents) =====
    ResourceItem(
        name=POLICY_JSON_STRICT,
        kind="policy",
        intent="policy.json",
        title="Strict JSON",
        description="For nodes that must return machine-parseable JSON; no prose.",
        body=(
            "You must return valid JSON that matches the requested schema exactly.\n"
            "Do not include extra keys, comments, Markdown, or natural language.\n"
            "If uncertain, return the closest valid JSON that satisfies the schema."
        ),
    ),
    ResourceItem(
        name=POLICY_STYLE_CONCISE,
        kind="policy",
        intent="policy.style",
        title="Style – concise",
        description="Short, direct sentences; remove filler and hedging.",
        body=(
            "Prefer short sentences and direct language.\n"
            "Avoid redundant preambles. Surface the answer first, then details.\n"
            "When listing steps or options, use clean bullet points."
        ),
    ),
    ResourceItem(
        name=POLICY_CITATIONS_MD,
        kind="policy",
        intent="policy.citations",
        title="Citations – Markdown",
        description="Inline bracketed citations + final Sources section.",
        body=(
            "Place citations immediately after the sentence(s) they support using a bracketed form like "
            "[Source: <file_name> p.<page>].\n"
            "End with a 'Sources' section listing each cited document once."
        ),
    ),

    # ===== Templates =====
    ResourceItem(
        name=TEMPLATE_ANSWER_CITED_V1,
        kind="template",
        intent="template.answer",
        title="Cited Answer v1",
        description="Answer + final Sources. Keep it compact.",
        body=(
            "## Answer\n"
            "{{answer}}\n\n"
            "## Sources\n"
            "{{#each citations}}\n"
            "- {{this}}\n"
            "{{/each}}\n"
        ),
    ),

    # ===== Tool instructions =====
    ResourceItem(
        name=TOOL_INSTR_VECTOR_SEARCH,
        kind="tool_instruction",
        intent="tool.instructions",
        title="Vector Search – tuning hints",
        description="Hints for adjusting top_k and respecting library tags across retries.",
        body=(
            "Start with top_k={{default_top_k}}. If no good candidates are found, increase top_k by +3 per retry, "
            "up to {{max_top_k}}.\n"
            "Respect active document libraries (tags). Prefer recent documents when relevance is tied."
        ),
    ),
    ResourceItem(
        name=TOOL_INSTR_TABULAR,
        kind="tool_instruction",
        intent="tool.instructions",
        title="Tabular SQL – usage hints",
        description="Guidance for describing target tables, constraints, and safe LIMITs.",
        body=(
            "Before generating SQL, ask for the table name(s), column meanings, and constraints if missing.\n"
            "Default to LIMIT {{default_limit}} unless the user specifies otherwise.\n"
            "Avoid destructive statements; SELECT only."
        ),
    ),
    ResourceItem(
        name=TOOL_INSTR_SUPERVISION,
        kind="tool_instruction",
        intent="tool.instructions",
        title="Supervision – metrics hints",
        description="Guidance for interpreting ops metrics and time windows.",
        body=(
            "Clarify the time window and scope before analyzing metrics. "
            "When anomalies are detected, propose 1–3 actionable checks with expected outcomes."
        ),
    ),
    ResourceItem(
        name=TOOL_INSTR_RESOURCES_MCP,
        kind="tool_instruction",
        intent="tool.instructions",
        title="Resources MCP – prompts & templates",
        description="How to list/create/update resources via the MCP server.",
        body=(
            "Use list endpoints before creating resources to prevent duplicates. "
            "When creating prompts/templates, confirm the target library_tag and a unique id.\n"
            "Return raw MCP output unless formatting is explicitly requested."
        ),
    ),

    # ===== Agent-level system prompts =====
    ResourceItem(
        name=AGENT_SYS_RAG,
        kind="prompt",
        intent="agent.system",
        title="Advanced RAG – system",
        description="Baseline identity and global rules for RAG; always cite; be grounded.",
        body=(
            "You are a grounded RAG assistant. Base answers on retrieved documents and include citations.\n"
            "If evidence is missing or weak, say so and suggest next steps.\n"
            "Be concise and precise. Current date: {{today}}."
        ),
        metadata={"agent": AGENT_RAG},
    ),
    ResourceItem(
        name=AGENT_SYS_TABULAR,
        kind="prompt",
        intent="agent.system",
        title="Tabular Expert – system",
        description="Helps users query structured/tabular data; careful SQL; explain assumptions.",
        body=(
            "You assist with querying structured/tabular data. Clarify the question, data source, and constraints.\n"
            "When proposing SQL, be safe (SELECT only), and explain assumptions briefly.\n"
            "Prefer incremental refinement over guessing. Current date: {{today}}."
        ),
        metadata={"agent": AGENT_TABULAR},
    ),
    ResourceItem(
        name=AGENT_SYS_SUPERVISION,
        kind="prompt",
        intent="agent.system",
        title="Supervision – system",
        description="Ops assistant: interpret metrics, spot anomalies, suggest focused checks.",
        body=(
            "You are an operations supervision assistant. You interpret metrics, logs, and status snapshots to find "
            "actionable issues.\n"
            "Always state the time window and scope. When you detect a risk, propose concrete next checks "
            "(1–3) with expected outcomes. Current date: {{today}}."
        ),
        metadata={"agent": AGENT_SUPERVISION},
    ),
    ResourceItem(
        name=AGENT_SYS_CONTENT_ADMIN,
        kind="prompt",
        intent="agent.system",
        title="Content Admin – system",
        description="Assistant for managing prompts/templates via MCP; enforces formatting rules.",
        body=(
            "You manage a library of prompts and templates via an MCP server.\n"
            "Distinguish clearly between creating a resource and using a template.\n"
            "Enforce the required YAML header/body separation and validate ids before creation.\n"
            "Ask for confirmation before destructive actions. Current date: {{today}}."
        ),
        metadata={"agent": AGENT_CONTENT_ADMIN},
    ),

    # ===== Node-level: Advanced RAG =====
    ResourceItem(
        name="node.system/grade_documents.permissive",
        kind="prompt",
        intent="node.system",
        node_key="grade_documents",
        title="Grade Documents – permissive",
        description="Keep candidates unless clearly off-topic; strict JSON for binary decision.",
        body=(
            "You are a permissive relevance grader for retrieval-augmented generation.\n"
            "- Return 'yes' unless the document is clearly off-topic for the question.\n"
            "- Consider shared keywords, entities, acronyms, or overlapping semantics as relevant.\n"
            "- Minor mismatches or partial overlaps should still be 'yes'.\n"
            "Return JSON exactly: {\"binary_score\": \"yes\" | \"no\"}."
        ),
    ),
    ResourceItem(
        name="node.system/generate.answer_with_citations",
        kind="prompt",
        intent="node.system",
        node_key="generate",
        title="Generate – answer with citations",
        description="Synthesize from selected docs; cite claims; separate answer from sources.",
        body=(
            "Answer the user's question using only the provided document excerpts.\n"
            "Clearly distinguish facts from speculation. Include citations for claims derived from the documents."
        ),
    ),
    ResourceItem(
        name="node.system/rephrase_query.vectors",
        kind="prompt",
        intent="node.system",
        node_key="rephrase_query",
        title="Rephrase – vector retrieval",
        description="Rewrite query for vector search; preserve original language and intent.",
        body=(
            "Rewrite the input question into a version optimized for dense vector retrieval.\n"
            "Preserve the input language, entities, and intent. Do not invent new facts."
        ),
    ),
    ResourceItem(
        name="node.system/grade_answer.binary",
        kind="prompt",
        intent="node.system",
        node_key="grade_generation",
        title="Grade Answer – binary",
        description="Decide if the answer resolves the question; strict JSON.",
        body=(
            "Decide whether the answer resolves the question.\n"
            "Return JSON exactly: {\"binary_score\": \"yes\" | \"no\"}."
        ),
    ),

    # ===== Node-level: Tabular Expert (typical slots) =====
    ResourceItem(
        name="node.system/sql.plan",
        kind="prompt",
        intent="node.system",
        node_key="plan_query",
        title="Plan – clarify tabular task",
        description="Elicit table(s), columns, filters; decide if SQL or summary is needed.",
        body=(
            "Clarify which table(s), columns, filters, and time window are relevant.\n"
            "Decide whether a SQL query is needed; if so, confirm assumptions briefly."
        ),
    ),
    ResourceItem(
        name="node.system/sql.generate_safe",
        kind="prompt",
        intent="node.system",
        node_key="generate_sql",
        title="Generate SQL – safe SELECT",
        description="Produce safe, dialect-agnostic SQL; never destructive; include LIMIT.",
        body=(
            "Generate a safe SELECT-only SQL query for the user's intent.\n"
            "Include a LIMIT (default {{default_limit}}) unless the user requests otherwise.\n"
            "Avoid vendor-specific features unless explicitly required."
        ),
    ),
    ResourceItem(
        name="node.system/sql.explain_results",
        kind="prompt",
        intent="node.system",
        node_key="summarize_results",
        title="Explain – summarize tabular results",
        description="Summarize query results; note outliers; suggest next slice/dimension.",
        body=(
            "Summarize the result set succinctly. Highlight outliers or notable trends.\n"
            "Suggest one next slice or dimension that could clarify the finding."
        ),
    ),

    # ===== Node-level: Supervision (ops slots) =====
    ResourceItem(
        name="node.system/ops.analyze_window",
        kind="prompt",
        intent="node.system",
        node_key="analyze_window",
        title="Analyze – metrics window",
        description="State scope/time window; identify anomalies; propose focused checks.",
        body=(
            "State the scope and time window being analyzed.\n"
            "Identify anomalies or risks and propose 1–3 focused checks with expected outcomes."
        ),
    ),
    ResourceItem(
        name="node.system/ops.summarize_findings",
        kind="prompt",
        intent="node.system",
        node_key="summarize_findings",
        title="Summarize – findings",
        description="Compact summary for operators; prioritize impact and next actions.",
        body=(
            "Provide a compact summary for operators. Prioritize user impact, blast radius, and next actions."
        ),
    ),

    # ===== Node-level: Content Admin assistant (MCP resources) =====
    ResourceItem(
        name="node.system/resources.create_or_use",
        kind="prompt",
        intent="node.system",
        node_key="reasoner",
        title="Resources – create vs use",
        description="Enforce distinction: creating prompts/templates vs using templates.",
        body=(
            "When asked to generate content from a template, do not create a new template. "
            "Fill the existing template's {variables} with provided values and return the result.\n"
            "When creating a resource, ensure YAML header + body separated by '---', and confirm library_tag + id."
        ),
    ),
]


# ---------- Agent bindings (defaults) ----------

_AGENTS: List[AgentBinding] = [

    # Advanced RAG (Remulus)
    AgentBinding(
        name=AGENT_RAG,
        display_name="AdvancedRagExpert",
        system_prompt_id=AGENT_SYS_RAG,
        node_overrides=[
            AgentNodeOverride(
                node_key="grade_documents",
                prompt_id="node.system/grade_documents.permissive",
                policies=[POLICY_JSON_STRICT],
            ),
            AgentNodeOverride(
                node_key="generate",
                prompt_id="node.system/generate.answer_with_citations",
                policies=[POLICY_STYLE_CONCISE, POLICY_CITATIONS_MD],
                template_id=TEMPLATE_ANSWER_CITED_V1,
            ),
            AgentNodeOverride(
                node_key="rephrase_query",
                prompt_id="node.system/rephrase_query.vectors",
                policies=[POLICY_JSON_STRICT],
            ),
            AgentNodeOverride(
                node_key="grade_generation",
                prompt_id="node.system/grade_answer.binary",
                policies=[POLICY_JSON_STRICT],
            ),
        ],
        default_policies=[],
    ),

    # Tabular Expert
    AgentBinding(
        name=AGENT_TABULAR,
        display_name="TabularExpert",
        system_prompt_id=AGENT_SYS_TABULAR,
        node_overrides=[
            AgentNodeOverride(
                node_key="plan_query",
                prompt_id="node.system/sql.plan",
                policies=[POLICY_STYLE_CONCISE],
            ),
            AgentNodeOverride(
                node_key="generate_sql",
                prompt_id="node.system/sql.generate_safe",
                policies=[POLICY_STYLE_CONCISE, POLICY_JSON_STRICT],
                template_id=None,
            ),
            AgentNodeOverride(
                node_key="summarize_results",
                prompt_id="node.system/sql.explain_results",
                policies=[POLICY_STYLE_CONCISE],
            ),
        ],
    ),

    # Supervision / Ops expert
    AgentBinding(
        name=AGENT_SUPERVISION,
        display_name="SupervisionExpert",
        system_prompt_id=AGENT_SYS_SUPERVISION,
        node_overrides=[
            AgentNodeOverride(
                node_key="analyze_window",
                prompt_id="node.system/ops.analyze_window",
                policies=[POLICY_STYLE_CONCISE],
            ),
            AgentNodeOverride(
                node_key="summarize_findings",
                prompt_id="node.system/ops.summarize_findings",
                policies=[POLICY_STYLE_CONCISE],
            ),
        ],
    ),

    # Content generator / admin assistant (Brontë)
    AgentBinding(
        name=AGENT_CONTENT_ADMIN,
        display_name="ContentGeneratorExpert",
        system_prompt_id=AGENT_SYS_CONTENT_ADMIN,
        node_overrides=[
            AgentNodeOverride(
                node_key="reasoner",
                prompt_id="node.system/resources.create_or_use",
                policies=[POLICY_STYLE_CONCISE],
            ),
        ],
    ),
]


# ---------- Exported default catalog ----------

DEFAULT_CATALOG = Catalog(
    version=1,
    library_tag="fred-core",
    items=_ITEMS,
    agents=_AGENTS,
)
DEFAULT_CATALOG.digest = DEFAULT_CATALOG.compute_digest()


# ---------- Convenience helpers (optional for seeders/UIs) ----------

def iter_items(kind: Optional[Kind] = None) -> List[ResourceItem]:
    """Return items, optionally filtered by kind."""
    if kind is None:
        return list(DEFAULT_CATALOG.items)
    return [i for i in DEFAULT_CATALOG.items if i.kind == kind]


def iter_agent_bindings() -> List[AgentBinding]:
    """Return all default agent bindings."""
    return list(DEFAULT_CATALOG.agents)


def find_item_by_id(item_id: str) -> Optional[ResourceItem]:
    """Lookup an item by id."""
    return next((i for i in DEFAULT_CATALOG.items if i.name == item_id), None)


def get_catalog_manifest() -> Dict[str, str]:
    """Small manifest for diagnostics / UI banners."""
    return {
        "library_tag": DEFAULT_CATALOG.library_tag,
        "version": str(DEFAULT_CATALOG.version),
        "digest": DEFAULT_CATALOG.digest or "",
        "created_at": DEFAULT_CATALOG.created_at,
    }
