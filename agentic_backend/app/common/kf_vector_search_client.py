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

# app/common/vector_search_client.py
from __future__ import annotations
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence
from pydantic import TypeAdapter
from fred_core import VectorSearchHit
import requests

from app.common.kf_base_client import KfBaseClient

logger = logging.getLogger(__name__)
_HITS = TypeAdapter(List[VectorSearchHit])


class VectorSearchClient(KfBaseClient):
    """Focused client for /vector/search (Rico’s domain)."""

    def search(
        self,
        *,
        query: str,
        top_k: int,
        tags: Optional[Sequence[str]] = None,
        payload_overrides: Optional[Dict[str, Any]] = None,
    ) -> List[VectorSearchHit]:
        """
        Why this shape:
        - 'payload_overrides' lets us experiment (filters/rerank) without widening the signature constantly.
        - We return validated models so agents/UI remain stable across backend tweaks.
        """
        payload: Dict[str, Any] = {"query": query, "top_k": top_k}
        if tags:
            payload["tags"] = list(tags)
        if payload_overrides:
            payload.update(payload_overrides)

        try:
            resp = self._post("/vector/search", json=payload)
        except (requests.ConnectionError, requests.Timeout):
            # Let orchestrators decide whether to skip/degrade
            raise

        resp.raise_for_status()
        raw = self._json_or_none(resp)
        if not isinstance(raw, Iterable):
            return []
        return _HITS.validate_python(raw)
