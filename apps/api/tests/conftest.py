import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:1/test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    # No context manager: lifespan (and the real DB pool) is not started in unit tests.
    return TestClient(app)
