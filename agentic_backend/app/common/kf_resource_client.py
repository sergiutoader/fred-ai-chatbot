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

# app/common/kf_resource_client.py
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
import requests

from app.common.kf_base_client import KfBaseClient, KfServiceUnavailable

logger = logging.getLogger(__name__)


class KfResourceClient(KfBaseClient):
    """
    Read-mostly client for KF *resources* (catalog, metadata).
    Callers often want to *skip gracefully* if KF is down, so we map transport errors to KfServiceUnavailable.
    """

    def list_resources(self, kind: str) -> List[Dict[str, Any]]:
        """GET /resources?kind=<kind>. Returns [] on 404; raises on other HTTP errors."""
        try:
            resp = self._get("/resources", params={"kind": kind})
        except (requests.ConnectionError, requests.Timeout) as e:
            raise KfServiceUnavailable(str(e)) from e

        if resp.status_code == 404:
            return []
        resp.raise_for_status()

        data = self._json_or_none(resp) or []
        return data if isinstance(data, list) else []

    def get_resource(self, resource_id: str) -> Optional[Dict[str, Any]]:
        """GET /resources/{id}. Returns None on 404; raises otherwise."""
        try:
            resp = self._get(f"/resources/{resource_id}")
        except (requests.ConnectionError, requests.Timeout) as e:
            raise KfServiceUnavailable(str(e)) from e

        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._json_or_none(resp)
