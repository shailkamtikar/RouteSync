import base64
import json
import time
import uuid

import jwt
import pytest

from app.domain import membership
from app.domain.membership import Membership

from .auth_helpers import OTHER_KEY, auth, make_token

OP1 = uuid.uuid4()
OP2 = uuid.uuid4()
USER1 = uuid.uuid4()


@pytest.fixture
def member_of_op1(monkeypatch):
    def fake(_conn, user_id):
        if user_id == USER1:
            return Membership(OP1, "Operator One", "active", "dispatcher")
        return None

    monkeypatch.setattr(membership, "fetch_membership", fake)


def test_me_with_valid_token(client, member_of_op1):
    r = client.get("/api/v1/me", headers=auth(make_token(USER1)))
    assert r.status_code == 200
    body = r.json()
    assert body["operator_id"] == str(OP1)
    assert body["role"] == "dispatcher"
    assert body["user_id"] == str(USER1)


def test_no_token_is_401(client, member_of_op1):
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Bearer", "Bearer   ", "Basic abc", "Bearer not-a-jwt", "x"])
def test_malformed_header_is_401(client, member_of_op1, header):
    assert client.get("/api/v1/me", headers={"Authorization": header}).status_code == 401


def test_expired_token_is_401(client, member_of_op1):
    token = make_token(USER1, exp=int(time.time()) - 10)
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 401


def test_token_signed_by_other_key_is_401(client, member_of_op1):
    token = make_token(USER1, key=OTHER_KEY)
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 401


def test_tampered_payload_is_401(client, member_of_op1):
    header, payload, signature = make_token(uuid.uuid4()).split(".")
    forged = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    forged["sub"] = str(USER1)
    forged_payload = base64.urlsafe_b64encode(json.dumps(forged).encode()).rstrip(b"=").decode()
    token = f"{header}.{forged_payload}.{signature}"
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 401


def test_alg_none_is_401(client, member_of_op1):
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(USER1), "aud": "authenticated", "role": "authenticated", "exp": now + 600},
        key=None,
        algorithm="none",
    )
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 401


def test_hs256_token_is_401(client, member_of_op1):
    token = jwt.encode(
        {"sub": str(USER1), "aud": "authenticated", "role": "authenticated", "exp": 9999999999},
        "a-shared-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "anon"},
        {"iss": "https://evil.example/auth/v1"},
        {"role": "anon"},
        {"role": "service_role"},
        {"sub": "not-a-uuid"},
        {"sub": None},
        {"exp": None},
    ],
)
def test_wrong_claims_are_401(client, member_of_op1, overrides):
    token = make_token(USER1, **overrides)
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 401


def test_valid_user_without_membership_is_403(client, member_of_op1):
    r = client.get("/api/v1/me", headers=auth(make_token(uuid.uuid4())))
    assert r.status_code == 403


def test_suspended_operator_is_403(client, monkeypatch):
    monkeypatch.setattr(
        membership,
        "fetch_membership",
        lambda _conn, _user: Membership(OP1, "Operator One", "suspended", "owner"),
    )
    assert client.get("/api/v1/me", headers=auth(make_token(USER1))).status_code == 403


def test_client_supplied_operator_id_is_ignored(client, member_of_op1):
    r = client.get(
        f"/api/v1/me?operator_id={OP2}",
        headers={**auth(make_token(USER1)), "X-Operator-Id": str(OP2)},
    )
    assert r.status_code == 200
    assert r.json()["operator_id"] == str(OP1)


def test_health_endpoints_stay_public(client):
    assert client.get("/healthz").status_code == 200


def test_token_issued_a_few_seconds_in_the_future_is_accepted(client, member_of_op1):
    soon = int(time.time()) + 5
    token = make_token(USER1, iat=soon, nbf=soon)
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 200


def test_token_issued_far_in_the_future_is_rejected(client, member_of_op1):
    later = int(time.time()) + 120
    token = make_token(USER1, iat=later, nbf=later)
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 401


def test_token_expired_within_leeway_is_still_accepted(client, member_of_op1):
    token = make_token(USER1, exp=int(time.time()) - 3)
    assert client.get("/api/v1/me", headers=auth(token)).status_code == 200
