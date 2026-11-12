"""API client wired to the rolled-back test connection, with ready-made auth headers."""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.db import get_conn
from app.main import app

from ..auth_helpers import auth, make_token


@dataclass
class Api:
    client: TestClient
    tenants: dict

    def headers(self, who: str) -> dict[str, str]:
        return auth(make_token(self.tenants[who]))

    def call(self, method: str, path: str, who: str | None = "owner1", **kwargs):
        headers = self.headers(who) if who else {}
        return self.client.request(method, f"/api/v1{path}", headers=headers, **kwargs)

    def get(self, path, who="owner1", **kwargs):
        return self.call("GET", path, who, **kwargs)

    def post(self, path, json=None, who="owner1", **kwargs):
        return self.call("POST", path, who, json=json, **kwargs)

    def patch(self, path, json=None, who="owner1", **kwargs):
        return self.call("PATCH", path, who, json=json, **kwargs)

    def put(self, path, json=None, who="owner1", **kwargs):
        return self.call("PUT", path, who, json=json, **kwargs)

    def delete(self, path, who="owner1", **kwargs):
        return self.call("DELETE", path, who, **kwargs)


@pytest.fixture
def api(conn, actor, tenants):
    actor.admin()

    def override():
        # Mirror production: a request that raises leaves no partial writes behind.
        with conn.transaction():
            yield conn

    app.dependency_overrides[get_conn] = override
    try:
        yield Api(TestClient(app), tenants)
    finally:
        app.dependency_overrides.pop(get_conn, None)
