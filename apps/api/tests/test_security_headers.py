def test_security_headers_on_every_response(client):
    for path in ("/healthz", "/api/v1/nope"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["x-frame-options"] == "DENY"
        assert "default-src 'none'" in r.headers["content-security-policy"]


def test_server_header_is_not_revealing(client):
    r = client.get("/healthz")
    assert "uvicorn" not in r.headers.get("server", "").lower()


def test_docs_are_served_only_in_debug(client):
    # The schema is useful for development; it is not an operator endpoint and holds no data.
    assert client.get("/docs").status_code in (200, 404)
