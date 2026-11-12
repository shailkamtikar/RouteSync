"""Helpers that mint test tokens signed with a throwaway key."""

import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import jwt as jwt_module

TEST_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def make_token(user_id: uuid.UUID | str | None = None, *, key=TEST_KEY, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user_id or uuid.uuid4()),
        "aud": "authenticated",
        "role": "authenticated",
        "iss": jwt_module._issuer(),
        "email": "user@routesync.test",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="ES256")


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
