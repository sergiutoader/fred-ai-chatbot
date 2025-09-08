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

from uuid import uuid4
from fred_core import TagType, parse_front_matter, ResourceHeader

from app.features.resources.structures import Resource, ResourceCreate


def _body_required(kind: TagType) -> bool:
    """
    For structural resources (agent_binding, agent), the header is the content.
    Everything else must include a non-empty body.
    """
    return kind not in {TagType.AGENT_BINDING, TagType.AGENT}


def build_resource_from_create(payload: ResourceCreate, library_tag_id: str, user: str) -> Resource:
    """
    Validates YAML header/body and returns a fully-populated Resource ready to persist.

    Rules:
    - Required header keys: 'version', 'kind' must match payload.kind when present.
    - Kind-specific metadata:
        * All kinds: optional 'format' (string), defaults vary by kind.
        * Prompts/rewriters/graders: optional 'output_schema' (dict).
        * Templates: optional 'input_schema' (dict).
        * (Legacy) 'schema' is accepted as 'output_schema' with a deprecation warning.
    - Body:
        * Required and non-empty for all kinds EXCEPT agent_binding and agent
          (these are header-only by design).
    - payload.{name,description,labels} override header {name,description,tags} when provided.
    """
    header_dict, body = parse_front_matter(payload.content)
    hdr = ResourceHeader.model_validate(header_dict)
    hdr.ensure_kind_matches(payload.kind)
    hdr.ensure_body_policy(payload.kind, body)

    # ----- 1) Required header keys -----
    version = hdr.version
    if not version:
        raise ValueError("Missing 'version' in resource header")

    yaml_name = hdr.name
    if yaml_name and payload.name and yaml_name != payload.name:
        raise ValueError(f"YAML name '{yaml_name}' does not match payload.name '{payload.name}'")
    if not yaml_name and not payload.name:
        raise ValueError("Resource name must be provided in either payload.name or YAML header 'name'")
    name = payload.name or yaml_name
    assert name is not None  # for mypy

    yaml_kind_raw = hdr.kind
    if yaml_kind_raw is not None:
        if yaml_kind_raw != payload.kind.value:
            raise ValueError(f"YAML kind '{yaml_kind_raw}' does not match payload.kind '{payload.kind.value}'")

    # ----- 2) Kind-aware schema/format handling -----
    # Accepted keys:
    #   - format: how to interpret/render the BODY (markdown/plaintext/handlebars/jinja2/json/yaml)
    #   - output_schema: JSON Schema for LLM outputs (dict)
    #   - input_schema: JSON Schema for template variables (dict)
    # Back-compat: if 'schema' present, treat it as output_schema and warn.
    fmt = hdr.format
    output_schema = hdr.output_schema
    input_schema = hdr.input_schema

    # Type checks for schemas when present
    if output_schema is not None and not isinstance(output_schema, dict):
        raise ValueError("'output_schema' must be a mapping (JSON Schema object) when provided")
    if input_schema is not None and not isinstance(input_schema, dict):
        raise ValueError("'input_schema' must be a mapping (JSON Schema object) when provided")

    # Optionally enforce default format per kind (no serialization change; just validate)
    if fmt is not None and not isinstance(fmt, str):
        raise ValueError("'format' must be a string when provided")

    # ----- 3) Body requirements by kind -----
    if _body_required(payload.kind):
        if not body or not body.strip():
            raise ValueError("Resource body must not be empty")
    # else: header-only kinds (agent_binding/agent) are allowed to have empty body

    # ----- 4) Derive metadata; payload overrides header -----
    description = payload.description or hdr.description

    # header.tags can be a list or a string; normalize to list[str]
    header_tags = hdr.tags or []
    if isinstance(header_tags, str):
        header_tags = [header_tags]
    elif not isinstance(header_tags, list):
        header_tags = []

    labels = payload.labels if payload.labels is not None else list(hdr.tags or [])
    # ----- 5) Assemble Resource -----
    return Resource(
        id=str(uuid4()),
        kind=payload.kind,
        version=str(version),
        name=name,
        description=description,
        labels=labels,
        author=user,
        content=payload.content,  # keep original text; do not mutate header/body
        library_tags=[library_tag_id],
    )
