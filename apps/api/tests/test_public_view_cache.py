import uuid

from app.api.v1 import public_track as pt
from app.config import get_settings


def test_view_cache_hits_and_invalidates(monkeypatch):
    monkeypatch.setattr(get_settings(), "public_view_cache_s", 60.0)
    pt._view_cache.clear()
    journey = uuid.uuid4()
    assert pt._cached("tok") is None
    pt._remember("tok", journey, {"journey": {"status": "in_progress"}})
    assert pt._cached("tok") == {"journey": {"status": "in_progress"}}
    pt.invalidate_view(uuid.uuid4())
    assert pt._cached("tok") is not None
    pt.invalidate_view(journey)
    assert pt._cached("tok") is None


def test_view_cache_disabled_when_ttl_is_zero(monkeypatch):
    monkeypatch.setattr(get_settings(), "public_view_cache_s", 0.0)
    pt._view_cache.clear()
    pt._remember("tok", uuid.uuid4(), {"x": 1})
    assert pt._cached("tok") is None
