from app.auth import tokens
from app.auth.rate_limit import RateLimiter


def test_tokens_are_long_unique_and_url_safe():
    made = {tokens.generate_token() for _ in range(1000)}
    assert len(made) == 1000
    assert all(len(t) >= 43 and t.replace("-", "").replace("_", "").isalnum() for t in made)


def test_hash_is_stable_peppered_and_not_the_token():
    token = tokens.generate_token()
    digest = tokens.hash_token(token)
    assert digest == tokens.hash_token(token) and len(digest) == 64 and digest != token
    assert tokens.tokens_match(token, digest)
    assert not tokens.tokens_match(token + "x", digest)
    import hashlib

    assert digest != hashlib.sha256(token.encode()).hexdigest()  # the pepper is mixed in


def test_rate_limiter_blocks_over_the_limit_and_recovers():
    now = [0.0]
    limiter = RateLimiter(limit=3, window_s=10, clock=lambda: now[0])
    assert [limiter.allow("a")[0] for _ in range(4)] == [True, True, True, False]
    allowed, retry = limiter.allow("a")
    assert not allowed and 0 < retry <= 10
    assert limiter.allow("b")[0] is True  # keys are independent
    now[0] = 10.1
    assert limiter.allow("a")[0] is True


def test_rate_limiter_cost():
    limiter = RateLimiter(limit=5, window_s=10, clock=lambda: 0.0)
    assert limiter.allow("a", cost=5)[0] is True
    assert limiter.allow("a")[0] is False
