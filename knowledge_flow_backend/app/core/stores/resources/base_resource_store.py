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

from abc import ABC, abstractmethod
from typing import List
from fred_core import TagType
from app.features.resources.structures import Resource


class ResourceNotFoundError(Exception):
    """Raised when a resource is not found."""

    pass


class ResourceAlreadyExistsError(Exception):
    """Raised when trying to create a resource that already exists."""

    pass


class BaseResourceStore(ABC):
    """
    Abstract base class for storing and retrieving resources, user-scoped.

    Exceptions:
        - list_resources_for_user: should not raise
        - get_resource_by_id: ResourceNotFoundError if not found
        - create_resource: ResourceAlreadyExistsError if already exists
        - update_resource: ResourceNotFoundError if not found
        - delete_resource: ResourceNotFoundError if not found
    """

    @abstractmethod
    def get_all_resources(self, kind: TagType) -> list[Resource]:
        pass

    def resource_exists(self, *, name: str, kind: TagType, library_tag_id: str) -> bool:
        """
        Checks if a resource with the given name, kind, and library tag ID already exists.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    @abstractmethod
    def get_resource_by_id(self, id: str) -> Resource:
        pass

    @abstractmethod
    def create_resource(self, resource: Resource) -> Resource:
        pass

    @abstractmethod
    def update_resource(self, id: str, resource: Resource) -> Resource:
        pass

    @abstractmethod
    def delete_resource(self, id: str) -> None:
        pass

    @abstractmethod
    def get_resources_in_tag(self, tag_id: str) -> List[Resource]:
        """
        Retrieve all resources associated with a specific tag.
        Raises:
            ResourceNotFoundError: If no resources are found for the tag.
        """
        pass

    @abstractmethod
    def search(self, *, name: str, kind: TagType, library_tag_name: str) -> List[Resource]:
        """
        Search for resources based on name, kind, and library tag name.
        Returns a list of resource dictionaries matching the criteria.
        """
        pass    
