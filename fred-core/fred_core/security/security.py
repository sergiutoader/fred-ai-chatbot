# fred_core/security/security.py

import logging
from fastapi import Security, HTTPException
from fastapi.security import OAuth2PasswordBearer
from fred_core.security.structure import User
from fred_core.security import security_provider

logger = logging.getLogger(__name__)

# OAuth2 scheme used to extract bearer token from requests
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

def initialize_security(config):
    """
    Should be called once at application startup.
    It sets up the OIDC provider with the given configuration.
    """
    security_provider.initialize_oidc(config)

def get_current_user(token: str = Security(oauth2_scheme)) -> User:
    """
    Use this in FastAPI routes to protect endpoints.
    Decodes the JWT token and returns the authenticated User.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    return security_provider.decode_token(token)
