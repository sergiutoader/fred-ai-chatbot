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

from fastapi import APIRouter
from app.application_context import get_app_context
from fred_core.security.structure import Security

class SecurityController:
    def __init__(self, router: APIRouter):
        self.router = router
        self.register_routes()

    def register_routes(self):
        @self.router.get("/config/security", response_model=Security, tags=["Configuration"])
        def get_security_config():
            return get_app_context().configuration.security
