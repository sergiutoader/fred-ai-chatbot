# fred_core/security/security_provider.py

import logging
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException
from typing import Any
from fred_core.security.structure import User

# Logger local
logger = logging.getLogger(__name__)

# Config globale (sera injectée dynamiquement)
CONFIG = None
JWKS_CLIENT: PyJWKClient | None = None


def initialize_oidc(config):
    """
    Initialise le client OIDC avec la configuration externe (type pydantic).
    - jwks_url : URL publique des clés (signatures)
    - issuer : attendu dans les tokens
    - claims_mapping : dictionnaire de correspondance des champs utilisateur
    """
    global CONFIG, JWKS_CLIENT
    CONFIG = config.security
    if not CONFIG.enabled:
        logger.warning("OIDC disabled — fallback to mock user")
        return

    try:
        JWKS_CLIENT = PyJWKClient(CONFIG.jwks_url)
        logger.info(f"OIDC initialized for issuer: {CONFIG.issuer}")
    except Exception as e:
        logger.error(f"Failed to initialize JWKS client: {e}")
        raise RuntimeError("Failed to initialize security provider")


def extract_claim(payload: dict, path: str) -> Any:
    """
    Extraction récursive de claims imbriqués depuis le JWT.
    Ex: "resource_access.my-client.roles"
    """
    keys = path.split(".")
    value = payload
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def decode_token(token: str) -> User:
    """
    Décode un JWT en utilisateur (générique OIDC).
    Utilise la conf déclarée dans CONFIG.claims_mapping pour extraire les infos.
    """
    if CONFIG is None or not CONFIG.enabled:
        logger.warning("Auth disabled — returning default admin user.")
        return User(uid="admin", username="admin", roles=["admin"], email="admin@local")

    try:
        # Récupération de la clé publique à partir du token
        signing_key = JWKS_CLIENT.get_signing_key_from_jwt(token).key

        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=CONFIG.issuer,
            options={"verify_aud": False},  # désactivé sauf si tu gères plusieurs audiences
        )

        mapping = CONFIG.claims_mapping

        user = User(
            uid=extract_claim(payload, mapping.get("sub", "sub")),
            username=extract_claim(payload, mapping.get("preferred_username", "preferred_username")),
            email=extract_claim(payload, mapping.get("email", "email")),
            roles=extract_claim(payload, mapping.get("roles", "roles")) or [],
        )

        logger.debug(f"Authenticated user: {user}")
        return user

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected JWT decoding error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Token validation failed")
