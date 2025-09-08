# fred_core/resources/header_models.py
from __future__ import annotations
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from fred_core.resources.frontmatter import body_required
from fred_core.resources.tags import TagType

class ResourceHeader(BaseModel):
    """
    Minimal, shared view of what's in the YAML header.
    Keep this independent of any persistence model.
    """
    name: str
    version: str
    kind: str
    intent: Optional[str] = None
    node_key: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    format: Optional[str] = None
    # Optional schemas (when applicable)
    output_schema: Optional[Dict[str, Any]] = None
    input_schema: Optional[Dict[str, Any]] = None
    # Optional tags/labels found in the header
    tags: List[str] = Field(default_factory=list)

    def ensure_body_policy(self, kind_enum: TagType, body: str) -> None:
        """
        Enforce the architectural rule: some kinds require a non-empty body.
        """
        if body_required(kind_enum) and not (body and body.strip()):
            raise ValueError("Resource body must not be empty for kind={}".format(kind_enum.value))

    def ensure_kind_matches(self, kind_enum: TagType) -> None:
        if self.kind != kind_enum.value:
            raise ValueError(f"YAML kind '{self.kind}' does not match expected '{kind_enum.value}'")
