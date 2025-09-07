
# fred_core/security/system_actor.py
import os
from typing import List
from fred_core.security.structure import KeycloakUser  # your existing type

# Defaults are explicit and environment-overridable.
_DEF_UID = "system:fred-core"
_DEF_USERNAME = "fred-core@bootstrap"
_DEF_EMAIL = "noreply+fred-core@localhost"
_DEF_ROLES = ["admin", "bootstrap"]

def get_system_actor() -> KeycloakUser:
    """
    Returns a KeycloakUser representing the system actor, with details
    configurable via environment variables.
    """
    uid = os.getenv("FRED_SYSTEM_ACTOR_UID", _DEF_UID)
    username = os.getenv("FRED_SYSTEM_ACTOR_USERNAME", _DEF_USERNAME)
    email = os.getenv("FRED_SYSTEM_ACTOR_EMAIL", _DEF_EMAIL)
    roles_env = os.getenv("FRED_SYSTEM_ACTOR_ROLES", ",".join(_DEF_ROLES))
    roles: List[str] = [r.strip() for r in roles_env.split(",") if r.strip()]
    return KeycloakUser(uid=uid, username=username, roles=roles, email=email)
