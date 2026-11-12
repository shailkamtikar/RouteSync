import os

os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:1/test"
os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    # No context manager: lifespan (and the real DB pool) is not started in unit tests.
    from app.db import get_conn

    app.dependency_overrides[get_conn] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.pop(get_conn, None)


@pytest.fixture(autouse=True)
def _test_signing_key(monkeypatch):
    """Unit tests verify tokens against a throwaway key instead of fetching the real JWKS."""
    from app.auth import jwt as jwt_module

    from .auth_helpers import TEST_KEY

    monkeypatch.setattr(jwt_module, "resolve_signing_key", lambda _token: TEST_KEY.public_key())


pytest_plugins = ["tests.db.api_fixtures"]
