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

from datetime import datetime, timezone
from typing import Tuple, Dict
import re
from uuid import uuid4

import yaml

from app.features.resources.structures import Resource, ResourceCreate, ResourceKind

_DASH_LINE_RE = re.compile(r"^\s*---\s*$")


def _body_required(kind: ResourceKind) -> bool:
    """
    For structural resources (agent_binding, agent), the header is the content.
    Everything else must include a non-empty body.
    """
    return kind not in {ResourceKind.AGENT_BINDING, ResourceKind.AGENT}


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
    header, body = parse_front_matter(payload.content)

    # ----- 1) Required header keys -----
    version = header.get("version")
    if not version:
        raise ValueError("Missing 'version' in resource header")

    yaml_kind = header.get("kind")
    if yaml_kind and yaml_kind != payload.kind.value:
        raise ValueError(f"YAML kind '{yaml_kind}' does not match payload.kind '{payload.kind.value}'")

    yaml_name = header.get("name")
    if yaml_name and payload.name and yaml_name != payload.name:
        raise ValueError(f"YAML name '{yaml_name}' does not match payload.name '{payload.name}'")
    if not yaml_name and not payload.name:
        raise ValueError("Resource name must be provided in either payload.name or YAML header 'name'")
    name = payload.name or yaml_name
    assert name is not None  # for mypy

    # ----- 2) Kind-aware schema/format handling -----
    # Accepted keys:
    #   - format: how to interpret/render the BODY (markdown/plaintext/handlebars/jinja2/json/yaml)
    #   - output_schema: JSON Schema for LLM outputs (dict)
    #   - input_schema: JSON Schema for template variables (dict)
    # Back-compat: if 'schema' present, treat it as output_schema and warn.
    fmt = header.get("format")  # optional
    output_schema = header.get("output_schema")
    input_schema = header.get("input_schema")

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
    description = payload.description or header.get("description")

    # header.tags can be a list or a string; normalize to list[str]
    header_tags = header.get("tags") or []
    if isinstance(header_tags, str):
        header_tags = [header_tags]
    elif not isinstance(header_tags, list):
        header_tags = []

    labels = payload.labels if payload.labels is not None else header_tags

    # ----- 5) Assemble Resource -----
    now = datetime.now(timezone.utc)
    return Resource(
        id=str(uuid4()),
        kind=payload.kind,
        version=str(version),
        name=name,
        description=description,
        labels=labels,
        author=user,
        created_at=now,
        updated_at=now,
        content=payload.content,  # keep original text; do not mutate header/body
        library_tags=[library_tag_id],
    )


def parse_front_matter(content: str) -> Tuple[Dict, str]:
    """
    Split a resource file into YAML header (dict) and body (str).

    Supported forms:
    1) Header first, then a single line '---' separator, then body
       id: ...
       version: v1
       kind: template
       ---
       <body>

    2) Classic front-matter with opening and closing '---'
       ---
       id: ...
       version: v1
       kind: template
       ---
       <body>
    """
    if content is None:
        raise ValueError("Empty content")

    # normalize newlines, strip BOM if present
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")

    lines = text.split("\n")
    n = len(lines)

    # Case A: starts with '---' (classic)
    if n > 0 and _DASH_LINE_RE.match(lines[0]):
        # find closing '---'
        try:
            end_idx = next(i for i in range(1, n) if _DASH_LINE_RE.match(lines[i]))
        except StopIteration:
            raise ValueError("Unclosed front-matter: expected closing '---' line")

        header_text = "\n".join(lines[1:end_idx]).strip()
        body = "\n".join(lines[end_idx + 1 :])
    else:
        # Case B: header first, then a single '---'
        try:
            sep_idx = next(i for i in range(0, n) if _DASH_LINE_RE.match(lines[i]))
        except StopIteration:
            raise ValueError("Missing '---' separator between header and body")

        header_text = "\n".join(lines[:sep_idx]).strip()
        body = "\n".join(lines[sep_idx + 1 :])

    if not header_text:
        raise ValueError("Empty YAML header before '---'")

    try:
        header = yaml.safe_load(header_text)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML header: {e}") from e

    if not isinstance(header, dict):
        raise ValueError("YAML header must be a mapping (key: value)")

    return header, body
