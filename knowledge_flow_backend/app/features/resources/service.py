# app/features/resource/service.py

import logging
from typing import List
from fred_core import (
    TagType, 
    timestamp, 
    utc_now, 
    AgentBindingHeader, 
    ResourceHeader, 
    parse_front_matter
)
from pydantic import ValidationError
from app.application_context import ApplicationContext
from app.core.stores.resources.base_resource_store import ResourceAlreadyExistsError, ResourceNotFoundError
from app.features.resources.utils import build_resource_from_create
from .structures import Resource, ResourceCreate, ResourceUpdate

logger = logging.getLogger(__name__)


class ResourceService:
    def __init__(self):
        context = ApplicationContext.get_instance()
        self._tag_store = context.get_tag_store()
        self._resource_store = context.get_resource_store()

    def create(self, *, library_tag_id: str, payload: ResourceCreate, user) -> Resource:
        resource = build_resource_from_create(payload, library_tag_id, user.username)

        if self._resource_store.resource_exists(name=resource.name, kind=resource.kind, library_tag_id=library_tag_id):
            raise ResourceAlreadyExistsError(f"A resource with the name '{resource.name}' and kind '{resource.kind}' already exists in library '{library_tag_id}'.")
        res = self._resource_store.create_resource(resource=resource)
        logger.info(f"[RESOURCES] Created resource {res.name} of kind {res.kind} for user {user.username}")
        return res

    def update(self, *, id: str, payload: ResourceUpdate, user) -> Resource:
        res = self._resource_store.get_resource_by_id(id)
        res.content = payload.content if payload.content is not None else res.content
        res.name = payload.name if payload.name is not None else res.name
        res.description = payload.description if payload.description is not None else res.description
        res.labels = payload.labels if payload.labels is not None else res.labels
        res.updated_at = timestamp(as_datetime=True)
        updated = self._resource_store.update_resource(id=id, resource=res)
        return updated

    def get(self, *, id: str, user) -> Resource:
        return self._resource_store.get_resource_by_id(id)

    def list_resources_by_kind(self, *, kind: TagType) -> list[Resource]:
        return self._resource_store.get_all_resources(kind=kind)

    def delete(self, *, id: str) -> None:
        self._resource_store.delete_resource(id=id)

    # ---------- Membership helpers ----------

    def get_resource_ids_for_tag(self, kind: TagType, tag_id: str) -> list[str]:
        all_resources = self._resource_store.get_all_resources(kind=kind)
        return [res.id for res in all_resources if tag_id in res.library_tags]

    def get_resources_for_tag(self, kind: TagType, tag_id: str) -> list[Resource]:
        all_resources = self._resource_store.get_all_resources(kind=kind)
        return [res for res in all_resources if tag_id in res.library_tags]

    def add_tag_to_resource(self, resource_id: str, tag_id: str) -> Resource:
        res = self._resource_store.get_resource_by_id(id=resource_id)
        if tag_id not in res.library_tags:
            res.library_tags.append(tag_id)
            res.updated_at = utc_now()
            res = self._resource_store.update_resource(id=res.id, resource=res)
        return res

    def remove_tag_from_resource(self, resource_id: str, tag_id: str, *, delete_if_orphan: bool = True) -> None:
        res = self._resource_store.get_resource_by_id(id=resource_id)
        if tag_id in res.library_tags:
            res.library_tags.remove(tag_id)
            if not res.library_tags and delete_if_orphan:
                self._resource_store.delete_resource(id=res.id)
            else:
                res.updated_at = utc_now()
                self._resource_store.update_resource(id=res.id, resource=res)

    def remove_tag_from_resources(self, kind: TagType, tag_id: str) -> None:
        """Remove tag from all resources that have it; delete orphans."""
        for res in self.get_resources_for_tag(kind, tag_id):
            # This loop is smaller than scanning all resources
            if tag_id in res.library_tags:
                res.library_tags.remove(tag_id)
                if not res.library_tags:
                    self._resource_store.delete_resource(id=res.id)
                else:
                    res.updated_at = utc_now()
                    self._resource_store.update_resource(id=res.id, resource=res)

    def search_resources(self, name: str, kind: TagType, library_tag_id: str) -> List[Resource]:
        """
        Searches for resources based on name, kind, and logical library tag ID.
        """
        return  self._resource_store.get_resource_by_name(
            name=name, kind=kind, library_tag_id=library_tag_id  # Pass logical ID
        )

    def get_agent_binding_by_name(self, *, library_tag_id: str, agent_name: str) -> AgentBindingHeader:
        """
        Fred note (WHY reuse frontmatter utils):
        - We centralize YAML header/body parsing and rules (no ad-hoc '---' splitting).
        - Agent bindings are structural: header-only by design (body not required).
        - Return a typed Pydantic model so agents don't parse YAML at runtime.
        """
        logger.info(
            "[RESOURCES] get_agent_binding_by_name lib=%s agent=%s",
            library_tag_id, agent_name
        )

        # 1) Exact lookup by (name, kind, library)
        results = self._resource_store.get_resource_by_name(
            name=agent_name,
            kind=TagType.AGENT_BINDING,
            library_tag_id=library_tag_id,
        )
        if not results:
            logger.info("[RESOURCES] binding not found lib=%s agent=%s", library_tag_id, agent_name)
            raise ResourceNotFoundError(
                f"agent binding '{agent_name}' not found in '{library_tag_id}'"
            )

        res: Resource = results[0]
        logger.info(
            "[RESOURCES] binding candidate id=%s name=%s kind=%s libs=%s",
            getattr(res, "id", None), res.name, res.kind, getattr(res, "library_tags", [])
        )

        # 2) Parse YAML header/body with the central utility
        content = res.content or ""
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Agent binding '{agent_name}' has empty or non-string content")

        try:
            header_dict, body = parse_front_matter(content)
        except ValueError as e:
            logger.error("[RESOURCES] front-matter parse error for '%s': %s", agent_name, e)
            raise

        # 3) Validate the generic header + architectural rules
        try:
            rh = ResourceHeader.model_validate(header_dict)
            rh.ensure_kind_matches(TagType.AGENT_BINDING)
            # For AGENT_BINDING, body is NOT required (enforced centrally)
            rh.ensure_body_policy(TagType.AGENT_BINDING, body)
        except Exception as e:
            logger.error("[RESOURCES] header validation failed for '%s': %s", agent_name, e)
            raise

        # 4) Validate binding-specific schema on the same header dict
        try:
            binding = AgentBindingHeader.model_validate(header_dict)
        except ValidationError as ve:
            logger.error("[RESOURCES] AgentBindingHeader validation failed for '%s': %s", agent_name, ve)
            raise

        logger.info(
            "[RESOURCES] binding parsed: name=%s version=%s system_prompt_id=%s overrides=%d",
            getattr(binding, "name", agent_name),
            getattr(binding, "version", "v1"),
            getattr(binding, "system_prompt_id", None),
            len(getattr(binding, "node_overrides", []) or []),
        )
        return binding
