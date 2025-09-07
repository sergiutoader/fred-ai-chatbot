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

from __future__ import annotations

import logging
from typing import Optional

# Import the fred-core default catalog
from fred_core import (
    DEFAULT_CATALOG,
    ResourceItem,
    AgentBinding,
    get_system_actor,
)

from app.features.resources.service import ResourceService
from app.features.resources.structures import Resource, ResourceCreate, ResourceKind

logger = logging.getLogger(__name__)

# ------------------------------ helpers ------------------------------


def _labels_for(item: ResourceItem) -> list[str]:
    return [item.intent, f"kind:{item.kind}"] + ([f"node:{item.node_key}"] if item.node_key else []) + ([f"agent:{(item.metadata or {}).get('agent')}"] if (item.metadata or {}).get("agent") else [])


def _yaml_from_item(item: ResourceItem) -> str:
    """
    Produce a YAML front-matter + body that matches your Content/Resources conventions.
    The header carries id/version/kind/intent/node_key for clarity.
    """
    header_lines = [
        "---",
        f"name: {item.name}",
        f"version: {item.version}",
        f"kind: {item.kind}",
        f"intent: {item.intent}",
    ]
    if item.node_key:
        header_lines.append(f"node_key: {item.node_key}")
    if item.title:
        header_lines.append(f"title: {item.title!s}")
    if item.description:
        header_lines.append(f"description: {item.description!s}")
    header = "\n".join(header_lines)
    return f"{header}\n---\n{item.body.rstrip()}\n"


def _yaml_from_agent_binding(binding: AgentBinding) -> str:
    """
    Store agent bindings as AGENT resources:
    - system_prompt_id
    - optional default_policies
    - node_overrides: prompt_id, policies, template_id
    """
    lines = [
        "---",
        f"name: {binding.name}",
        "kind: agent_binding",
        "version: v1",
        f"display_name: {binding.display_name}",
        f"system_prompt_id: {binding.system_prompt_id}",
    ]
    if binding.default_policies:
        lines.append("default_policies:")
        for p in binding.default_policies:
            lines.append(f"  - {p}")
    if binding.node_overrides:
        lines.append("node_overrides:")
        for o in binding.node_overrides:
            lines.append(f"  - node_key: {o.node_key}")
            if o.prompt_id:
                lines.append(f"    prompt_id: {o.prompt_id}")
            if o.policies:
                lines.append("    policies:")
                for p in o.policies:
                    lines.append(f"      - {p}")
            if o.template_id:
                lines.append(f"    template_id: {o.template_id}")
    header = "\n".join(lines)
    # No body needed; the header is the full content for bindings
    return f"{header}\n---\n"


def _exists_by_name_in_library(
    svc: ResourceService,
    *,
    kind: ResourceKind,
    library_tag_id: str,
    resource_id: str,
) -> bool:
    """
    Idempotency check: does a resource with the same name already exist in this library?
    We fetch resources for the tag and scan by name.
    """
    try:
        resources: list[Resource] = svc.get_resources_for_tag(kind=kind, tag_id=library_tag_id)
        return any((r.name or "").strip() == resource_id.strip() for r in resources)
    except Exception:
        logger.warning("[BOOTSTRAP] Could not list resources to check existence; will try to create.", exc_info=True)
        return False


def _create_resource(
    svc: ResourceService,
    *,
    library_tag_id: str,
    kind: ResourceKind,
    name: str,
    description: Optional[str],
    content: str,
    labels: Optional[list[str]],
) -> Optional[Resource]:
    payload = ResourceCreate(
        kind=kind,
        content=content,
        name=name,
        description=description,
        labels=labels or [],
    )
    try:
        return svc.create(library_tag_id=library_tag_id, payload=payload, user=get_system_actor())
    except Exception:
        logger.warning("[BOOTSTRAP] Create failed for %s (%s)", name, kind, exc_info=True)
        return None


# ------------------------------ main entrypoint ------------------------------


def bootstrap_fred_core() -> dict:
    """
    Idempotently seed the fred-core library with catalog items and agent bindings.
    Returns a small summary dict for logs / UI.
    """
    svc = ResourceService()

    # 1) Ensure the library tag exists

    created = []
    skipped = []

    # 2) Seed items (prompts/templates/policies/tool-instructions)
    for item in DEFAULT_CATALOG.items:
        kind = ResourceKind(item.kind)
        if _exists_by_name_in_library(svc, kind=kind, library_tag_id=DEFAULT_CATALOG.library_tag, resource_id=item.name):
            skipped.append(item.name)
            continue

        res = _create_resource(
            svc,
            library_tag_id=DEFAULT_CATALOG.library_tag,
            kind=kind,
            name=item.name,
            description=item.description,
            content=_yaml_from_item(item),
            labels=_labels_for(item),
        )
        created.append(item.name) if res else skipped.append(item.name)

    # 3) Seed agent bindings as AGENT_BINDING resources
    for binding in DEFAULT_CATALOG.agents:
        kind = ResourceKind.AGENT_BINDING  # ← explicit new kind
        if _exists_by_name_in_library(svc, kind=kind, library_tag_id=DEFAULT_CATALOG.library_tag, resource_id=binding.name):
            skipped.append(f"agent:{binding.name}")
            continue

        res = _create_resource(
            svc,
            library_tag_id=DEFAULT_CATALOG.library_tag,
            kind=kind,
            name=binding.name,
            description=f"Default fred-core bindings for {binding.display_name}",
            content=_yaml_from_agent_binding(binding),
            labels=[f"agent:{binding.name}", "binding:default"],
        )
        created.append(f"agent:{binding.name}") if res else skipped.append(f"agent:{binding.name}")
    digest = DEFAULT_CATALOG.digest or ""
    summary = {
        "library_tag": DEFAULT_CATALOG.library_tag,
        "catalog_version": DEFAULT_CATALOG.version,
        "catalog_digest": digest,
        "created": created,
        "skipped": skipped,
        "total_items": len(DEFAULT_CATALOG.items),
        "total_agents": len(DEFAULT_CATALOG.agents),
    }
    logger.info("[BOOTSTRAP] fred-core seeded: %s", summary)
    return summary


# Allow running as a script (optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bootstrap_fred_core()
