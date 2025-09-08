import logging
from typing import Any, Dict, List

from fred_core import ThreadSafeLRUCache, TagType
from opensearchpy import OpenSearch, NotFoundError, ConflictError, RequestsHttpConnection

from app.core.stores.resources.base_resource_store import (
    BaseResourceStore,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
)
from app.features.resources.structures import Resource

logger = logging.getLogger(__name__)

RESOURCES_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "kind": {"type": "keyword"},  # "prompt" or "template"
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "description": {"type": "text"},
            "content": {"type": "text"},
            "library_tags": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            # Any additional fields go here
        }
    }
}


class OpenSearchResourceStore(BaseResourceStore):
    def __init__(
        self,
        host: str,
        index: str,
        username: str,
        password: str,
        secure: bool = False,
        verify_certs: bool = False,
    ):
        self.client = OpenSearch(
            host,
            http_auth=(username, password),
            use_ssl=secure,
            verify_certs=verify_certs,
            connection_class=RequestsHttpConnection,
        )
        self._cache = ThreadSafeLRUCache[str, Resource](max_size=1000)
        self.index_name = index

        if not self.client.indices.exists(index=self.index_name):
            self.client.indices.create(index=self.index_name, body=RESOURCES_INDEX_MAPPING)
            logger.info(f"[RESOURCES] OpenSearch index '{self.index_name}' created.")
        else:
            logger.info(f"[RESOURCES] OpenSearch index '{self.index_name}' already exists.")

    def list_resources_for_user(self, user: str, kind: TagType) -> List[Resource]:
        try:
            q = {"query": {"bool": {"must": [{"term": {"owner_id": user}}, {"term": {"kind": kind}}]}}}
            resp = self.client.search(index=self.index_name, body=q, params={"size": 10000})
            return [Resource(**hit["_source"]) for hit in resp["hits"]["hits"]]
        except Exception as e:
            logger.error(f"[RESOURCES] Failed to list {kind}s for user '{user}': {e}")
            raise

    def get_all_resources(self, kind: TagType) -> List[Resource]:
        try:
            q = {"query": {"term": {"kind": kind}}}
            resp = self.client.search(index=self.index_name, body=q, params={"size": 10000})
            return [Resource(**hit["_source"]) for hit in resp["hits"]["hits"]]
        except Exception as e:
            logger.error(f"[RESOURCES] Failed to list {kind}s: {e}")
            raise

    def get_resource_by_id(self, id: str) -> Resource:
        if cached := self._cache.get(id):
            return cached
        try:
            doc = self.client.get(index=self.index_name, id=id)
            return Resource(**doc["_source"])
        except NotFoundError:
            raise ResourceNotFoundError(f"resource '{id}' not found.")
        except Exception as e:
            logger.error(f"[RESOURCES] Failed to get resource '{id}': {e}")
            raise

    def create_resource(self, resource: Resource) -> Resource:
        try:
            self.client.index(
                index=self.index_name,
                id=resource.id,
                body=resource.model_dump(mode="json"),
            )
            self._cache.set(resource.id, resource)
            logger.info(f"[RESOURCES] Created {resource.kind} '{resource.id}'")
            return resource
        except ConflictError:
            raise ResourceAlreadyExistsError(f"{resource.kind} '{resource.id}' already exists.")
        except Exception as e:
            logger.error(f"[RESOURCES] Failed to create {resource.kind} '{resource.id}': {e}")
            raise

    def update_resource(self, id: str, resource: Resource) -> Resource:
        try:
            self.get_resource_by_id(id)  # ensure exists
            self.client.index(
                index=self.index_name,
                id=id,
                body=resource.model_dump(mode="json"),
            )
            self._cache.set(resource.id, resource)
            logger.info(f"[RESOURCES] Updated resource '{id}'")
            return resource
        except ResourceNotFoundError:
            raise
        except Exception as e:
            logger.error(f"[RESOURCES] Failed to update {resource.kind} '{id}': {e}")
            raise

    def delete_resource(self, id: str) -> None:
        self._cache.delete(id)
        try:
            self.client.delete(index=self.index_name, id=id)
            logger.info(f"[RESOURCES] Deleted resource '{id}'")
        except NotFoundError:
            raise ResourceNotFoundError(f"resource with id '{id}' not found.")
        except Exception as e:
            logger.error(f"[RESOURCES] Failed to delete resource '{id}': {e}")
            raise

    def get_resources_in_tag(self, tag_id: str) -> List[Resource]:
        try:
            q = {"query": {"bool": {"must": [{"term": {"library_tags": tag_id}}]}}}
            resp = self.client.search(index=self.index_name, body=q, params={"size": 10000})
            if not resp["hits"]["hits"]:
                raise ResourceNotFoundError(f"No resource found for tag '{tag_id}'")
            return [Resource(**hit["_source"]) for hit in resp["hits"]["hits"]]
        except ResourceNotFoundError:
            raise
        except Exception as e:
            logger.error(f"[RESOURCES] Failed to get resources for tag '{tag_id}': {e}")
            raise

    def resource_exists(self, *, name: str, kind: TagType, library_tag_id: str) -> bool:
        """
        Fred note (WHY this method is noisy now):
        - We're investigating why existence checks always return false.
        - We log *everything*: the normalized kind value, the query body, 
        and the raw response from OpenSearch.
        - Once stable, we can reduce this to a single debug/info line.
        """
        kind_value = kind.value  # Make enum explicit
        logger.info("========================================================================")
        logger.info(f"[RESOURCES] Checking existence for name='{name}', kind='{kind_value}', library_tag_id='{library_tag_id}'")

        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"name.keyword": name}},
                        {"term": {"kind": kind_value}},
                        {"term": {"library_tags": library_tag_id}},
                    ]
                }
            },
            "size": 1,
            "_source": True,  # show the hit’s source in logs for investigation
        }

        logger.info(f"[RESOURCES] Query body for existence check:\n{query}")

        try:
            resp = self.client.search(index=self.index_name, body=query)
            logger.info(f"[RESOURCES] Raw search response: {resp}")

            hits = resp.get("hits", {}).get("hits", [])
            logger.info(f"[RESOURCES] Number of hits: {len(hits)}")

            if hits:
                logger.info(f"[RESOURCES] First hit _source: {hits[0].get('_source')}")
                logger.info("========================================================================")
        
                return True
            else:
                logger.info("[RESOURCES] No hits found → returning False")
                logger.info("========================================================================")
                return False
            
        except Exception as e:
            logger.error(
                f"[RESOURCES] Exception during existence check for "
                f"name='{name}', kind='{kind_value}', library_tag_id='{library_tag_id}': {e}"
            )
            raise

        
    def get_resource_by_name(self, *, name: str, kind: TagType, library_tag_id: str) -> List[Resource]:
        """
        Executes a precise search for resources based on name, kind, and library tag name.
        """
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"name.keyword": name}},
                        {"term": {"kind": kind.value}},
                        {"term": {"library_tags": library_tag_id}}  # Search for the logical name
                    ]
                }
            }, 
            "size": 1,
            "_source": True, 
        }
        logger.info(f"[RESOURCES] Query body for get_resource_by_name:\n{query}")
        resp = self.client.search(index=self.index_name, body=query)
        logger.info(f"[RESOURCES] Raw search response: {resp}")
        return [Resource(**hit["_source"]) for hit in resp.get("hits", {}).get("hits", [])]

