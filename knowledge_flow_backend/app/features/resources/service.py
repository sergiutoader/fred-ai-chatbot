# app/features/resource/service.py

import logging
from typing import List
from fred_core import TagType, timestamp, utc_now
from app.application_context import ApplicationContext
from app.core.stores.resources.base_resource_store import ResourceAlreadyExistsError
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

    def search_resources(self, name: str, kind: TagType, library_tag_name: str) -> List[Resource]:
        """
        Searches for resources based on name, kind, and logical library tag ID.
        """
        return  self._resource_store.search(
            name=name, kind=kind, library_tag_name=library_tag_name  # Pass logical name
        )
