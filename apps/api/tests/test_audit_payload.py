import pytest

from app.domain.audit import AuditPayloadError, _check_payload


def test_plain_payload_is_accepted():
    _check_payload({"from": "draft", "to": "ready", "counts": [1, 2], "nested": {"ok": True}})


@pytest.mark.parametrize(
    "payload",
    [
        {"passenger_name": "Asha"},
        {"Phone": "+919800000000"},
        {"booking": {"seat_number": "12A"}},
        {"items": [{"contact_name": "Ravi"}]},
        {"token": "abc"},
    ],
)
def test_personal_data_is_rejected(payload):
    with pytest.raises(AuditPayloadError):
        _check_payload(payload)
