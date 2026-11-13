"""Verification of Supabase-issued access tokens (asymmetric keys published as JWKS)."""

import time
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


_known_keys: dict[str, object] = {}


def resolve_signing_key(token: str):
    """Return the public key for this token. Replaced in unit tests.

    Keys already seen are remembered, so a brief failure to reach the key endpoint does not
    sign every user out. An unknown key id is always looked up; it is never trusted blindly.
    """
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        kid = None
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            key = _jwks_client().get_signing_key_from_jwt(token).key
            if kid:
                _known_keys[kid] = key
            return key
        except jwt.exceptions.PyJWKClientConnectionError as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.3)
    if kid and kid in _known_keys:
        return _known_keys[kid]
    raise last_error  # type: ignore[misc]


# The real resolver, kept under a second name because tests replace `resolve_signing_key`.
default_resolve_signing_key = resolve_signing_key


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
