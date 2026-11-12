import pytest
from pydantic import ValidationError

from app import db
from app.config import Settings


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_ok(client, monkeypatch):
    monkeypatch.setattr(db, "check_db", lambda: True)
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["db"] == "ok"


def test_readyz_db_down(client, monkeypatch):
    monkeypatch.setattr(db, "check_db", lambda: False)
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "db": "unavailable"}
    assert "Traceback" not in r.text


def test_missing_config_fails_fast(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "database_url" in str(exc.value)


def test_request_id_generated(client):
    r = client.get("/healthz")
    assert len(r.headers["X-Request-ID"]) == 32


def test_request_id_echoed(client):
    r = client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"


def test_unknown_route_is_json_404(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_cors_blocks_unknown_origin(client):
    r = client.get("/healthz", headers={"Origin": "https://evil.test"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_allows_local_web(client):
    r = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
