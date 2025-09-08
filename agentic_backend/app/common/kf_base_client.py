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
import logging
from typing import Any, Callable, Dict, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.application_context import get_app_context

logger = logging.getLogger(__name__)
Json = Any


def _session_with_retries() -> requests.Session:
    """Why: make outbound calls resilient to transient 429/5xx; small backoff to preserve UX."""
    s = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


class KfServiceUnavailable(Exception):
    """Knowledge Flow unreachable (DNS/conn/timeout)."""

class KfResourceNotFoundError(Exception):
    """Raised when a resource is not found."""

    pass

class KfBaseClient:
    """
    Fred rationale:
    - Centralize outbound auth + single 401 refresh.
    - Timeouts + base URL come from config for ops control.
    - Keep plumbing here so feature clients stay focused.
    """

    def __init__(self):
        ctx = get_app_context()
        oa = ctx.get_outbound_auth()

        self.base_url: str = ctx.get_knowledge_flow_base_url().rstrip("/")
        tcfg = ctx.configuration.ai.timeout
        self.timeout: Tuple[float, float] = (
            float(tcfg.connect or 5),
            float(tcfg.read or 15),
        )
        self.session = _session_with_retries()
        self.session.auth = oa.auth
        self._on_auth_refresh: Optional[Callable[[], None]] = oa.refresh

    def _request_once(self, method: str, path: str, **kwargs) -> requests.Response:
        return self.session.request(
            method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs
        )

    def _request_with_auth_retry(
        self, method: str, path: str, **kwargs
    ) -> requests.Response:
        resp = self._request_once(method, path, **kwargs)
        if resp.status_code == 401 and self._on_auth_refresh:
            try:
                logger.info(
                    "401 from Knowledge Flow — refreshing token and retrying once."
                )
                self._on_auth_refresh()
            except Exception as e:
                logger.warning("Token refresh failed; returning original 401: %s", e)
                return resp
            resp = self._request_once(method, path, **kwargs)
        return resp

    def _get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request_with_auth_retry("GET", path, params=params)

    def _post(
        self, path: str, json: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request_with_auth_retry("POST", path, json=json)

    @staticmethod
    def _json_or_none(resp: requests.Response) -> Optional[Json]:
        try:
            return resp.json()
        except ValueError:
            logger.error(
                "Non-JSON response from %s %s", resp.request.method, resp.request.url
            )
            return None
