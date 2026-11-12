"""Verification of Supabase-issued access tokens (asymmetric keys published as JWKS)."""

import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient

from app.config import get_settings

ALLOWED_ALGORITHMS = ["ES256", "RS256"]
AUDIENCE = "authenticated"


class InvalidToken(Exception):
    """The token is missing, malformed, expired, or not issued by our Supabase project."""


@dataclass(frozen=True)
class TokenUser:
    user_id: uuid.UUID
    email: str | None


def _issuer() -> str:
    return f"{get_settings().supabase_url.rstrip('/')}/auth/v1"


@lru_cache
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(
        f"{_issuer()}/.well-known/jwks.json", cache_keys=True, lifespan=600, timeout=5
    )


def resolve_signing_key(token: str):
    """Return the public key for this token. Replaced in unit tests."""
    return _jwks_client().get_signing_key_from_jwt(token).key


def verify_access_token(token: str) -> TokenUser:
    try:
        key = resolve_signing_key(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=ALLOWED_ALGORITHMS,
            audience=AUDIENCE,
            issuer=_issuer(),
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
        if claims.get("role") != "authenticated":
            raise InvalidToken("not an authenticated user token")
        return TokenUser(user_id=uuid.UUID(claims["sub"]), email=claims.get("email"))
    except InvalidToken:
        raise
    except Exception as exc:  # any decode, key lookup or format failure means "not valid"
        raise InvalidToken(type(exc).__name__) from exc
