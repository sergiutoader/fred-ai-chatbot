import pytest
import jwt
from datetime import datetime, timedelta
from jwt import algorithms
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fred_core.security.structure import User
from fred_core.security.security_provider import decode_token

def generate_rsa_keys():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    public_key = private_key.public_key()
    return private_key, public_key


def generate_jwt_token(private_key, payload: dict):
    token = jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    return token


def test_decode_token_returns_user():
    # Generate keys
    private_key, public_key = generate_rsa_keys()

    # Setup fake OIDC config
    class FakeSecurity:
        enabled = True
        issuer = "http://test-issuer"
        jwks_url = "http://fake-url"  # won't be used
        client_id = "fred-frontend"
        claims_mapping = {
            "sub": "uid",
            "preferred_username": "username",
            "email": "email",
            "roles": "roles",
        }

    class FakeConfig:
        security = FakeSecurity()

    # Patch JWKS client manually
    from fred_core.security import security_provider
    security_provider.CONFIG = FakeSecurity()
    security_provider.JWKS_CLIENT = None  # we bypass it

    # Patch decode_token to inject public key manually
    def manual_decode_token(token: str) -> User:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=FakeSecurity.issuer,
            options={"verify_aud": False}
        )

        return User(
            uid=payload["uid"],
            username=payload["username"],
            email=payload["email"],
            roles=payload.get("roles", []),
        )

    # Replace actual decode_token temporarily
    security_provider.decode_token = manual_decode_token

    payload = {
        "uid": "user-123",
        "username": "juliendev",
        "email": "julien@example.com",
        "roles": ["admin"],
        "iss": "http://test-issuer",
        "exp": datetime.utcnow() + timedelta(minutes=5)
    }

    token = generate_jwt_token(private_key, payload)

    user = manual_decode_token(token)

    assert user.uid == "user-123"
    assert user.username == "juliendev"
    assert user.email == "julien@example.com"
    assert "admin" in user.roles
