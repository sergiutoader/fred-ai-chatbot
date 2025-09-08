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
# fred_core/resources/frontmatter.py

from __future__ import annotations
from typing import Tuple, Dict
import re
import yaml
from fred_core.resources.tags import TagType

_DASH_LINE_RE = re.compile(r"^\s*---\s*$")

def body_required(kind: TagType) -> bool:
    """
    Architectural rule:
    - Structural resources (AGENT_BINDING, AGENT) are *header-only*.
    - Everything else (PROMPT, TEMPLATE, POLICY, TOOL_INSTRUCTION, ...) must have a body.
    This keeps 'structure' separate from 'instructions/templates' text.
    """
    return kind not in {TagType.AGENT_BINDING, TagType.AGENT}

def parse_front_matter(content: str) -> Tuple[Dict, str]:
    """
    Split a resource text into YAML header (dict) and body (str).

    Supported forms:
    A) Classic:
       ---
       name: ...
       version: v1
       kind: prompt
       ---
       <body>

    B) Header-first then one '---' line:
       name: ...
       version: v1
       kind: prompt
       ---
       <body>

    Strictness:
    - Raises ValueError on missing/invalid header or missing '---'.
    - Normalizes newlines and strips BOM.
    """
    if content is None:
        raise ValueError("Empty content")

    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")

    lines = text.split("\n")
    n = len(lines)

    # Case A: starts with '---'
    if n > 0 and _DASH_LINE_RE.match(lines[0]):
        try:
            end_idx = next(i for i in range(1, n) if _DASH_LINE_RE.match(lines[i]))
        except StopIteration:
            raise ValueError("Unclosed front-matter: expected closing '---' line")
        header_text = "\n".join(lines[1:end_idx]).strip()
        body = "\n".join(lines[end_idx + 1 :])
    else:
        # Case B: header-first then '---'
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
