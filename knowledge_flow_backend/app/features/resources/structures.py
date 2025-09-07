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

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field
from fred_core import BaseModelWithId


class ResourceKind(str, Enum):
    """
    Resource kinds supported in fred-core. A resource is a piece of content
    such as a prompt, template, policy, tool instruction, or agent binding.
    They are encoded using a flexible YAML front-matter + body format.

    Note: some kinds (agent_binding, agent) are structural and do not require a body.
    """

    PROMPT = "prompt"
    TEMPLATE = "template"
    POLICY = "policy"
    TOOL_INSTRUCTION = "tool_instruction"
    AGENT = "agent"
    AGENT_BINDING = "agent_binding"
    MCP = "mcp"


class ResourceUpdate(BaseModel):
    """
    Schema for updating an existing resource.
    """

    content: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    labels: Optional[List[str]] = None


class ResourceCreate(BaseModel):
    """
    Schema for creating a new resource.
    The 'content' field must include YAML front-matter with at least 'version', 'kind', name,
    input_schema and output_schema as applicable, and the body if required by kind.
    """

    kind: ResourceKind
    content: str
    name: Optional[str] = None
    description: Optional[str] = None
    labels: Optional[List[str]] = None


class Resource(BaseModelWithId):
    """
    Full representation of a Resource as stored in the system.
    The 'content' field includes the full YAML front-matter + body.
    """

    kind: ResourceKind
    version: str
    name: str
    description: Optional[str] = None
    labels: Optional[List[str]] = None
    author: str
    created_at: datetime
    updated_at: datetime
    content: str = Field(..., description="Raw YAML text or other content")
    library_tags: List[str] = Field(..., description="List of tags associated with the resource")
