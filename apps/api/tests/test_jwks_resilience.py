import jwt
import pytest

from app.auth import jwt as jwt_module

from .auth_helpers import TEST_KEY, make_token


class FlakyClient:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def get_signing_key_from_jwt(self, token):
        self.calls += 1
        if self.calls <= self.failures:
            raise jwt.exceptions.PyJWKClientConnectionError("network down")

        class Key:
            key = TEST_KEY.public_key()

        return Key()


@pytest.fixture
def real_resolver(monkeypatch):
    """Put the real resolver back (the suite normally replaces it with a test key)."""
    monkeypatch.setattr(jwt_module, "resolve_signing_key", jwt_module.default_resolve_signing_key)
    monkeypatch.setattr(jwt_module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(jwt_module, "_known_keys", {})
    return jwt_module


def token_with_kid(kid="k1"):
    return jwt.encode({"sub": "x"}, TEST_KEY, algorithm="ES256", headers={"kid": kid})


def test_one_network_failure_is_retried(real_resolver, monkeypatch):
    client = FlakyClient(failures=1)
    monkeypatch.setattr(real_resolver, "_jwks_client", lambda: client)
    assert real_resolver.resolve_signing_key(token_with_kid()) is not None
    assert client.calls == 2


def test_known_key_is_used_while_the_endpoint_is_unreachable(real_resolver, monkeypatch):
    good = FlakyClient(failures=0)
    monkeypatch.setattr(real_resolver, "_jwks_client", lambda: good)
    real_resolver.resolve_signing_key(token_with_kid("k1"))
    down = FlakyClient(failures=99)
    monkeypatch.setattr(real_resolver, "_jwks_client", lambda: down)
    assert real_resolver.resolve_signing_key(token_with_kid("k1")) is not None


def test_unknown_key_is_never_trusted_when_the_endpoint_is_unreachable(real_resolver, monkeypatch):
    monkeypatch.setattr(real_resolver, "_jwks_client", lambda: FlakyClient(failures=99))
    with pytest.raises(jwt.exceptions.PyJWKClientConnectionError):
        real_resolver.resolve_signing_key(token_with_kid("never-seen"))
    with pytest.raises(real_resolver.InvalidToken):
        real_resolver.verify_access_token(token_with_kid("never-seen"))


def test_tokens_still_verify_end_to_end_with_the_patched_resolver():
    assert jwt_module.verify_access_token(make_token()).user_id is not None
