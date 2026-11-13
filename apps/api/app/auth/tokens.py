"""Random access tokens for devices and public links. Only peppered hashes are stored."""

import hashlib
import hmac
import secrets

from app.config import get_settings


def generate_token() -> str:
    """256 bits of randomness, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    pepper = get_settings().public_token_pepper
    return hashlib.sha256(f"{pepper}{token}".encode()).hexdigest()


def tokens_match(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)
