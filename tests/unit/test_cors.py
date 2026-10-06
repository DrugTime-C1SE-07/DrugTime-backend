"""CORS chỉ bật cho origin được cấu hình (AC4)."""

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.shared.config import get_settings

ALLOWED = "http://localhost:5000"


def _preflight(origins: str, origin: str, monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origins)
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        return client.options(
            "/auth/mobile/otp",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    finally:
        get_settings.cache_clear()


def test_allowed_origin_preflight(monkeypatch):
    r = _preflight(f"{ALLOWED}, http://127.0.0.1:5000", ALLOWED, monkeypatch)

    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ALLOWED
    assert "access-control-allow-credentials" not in r.headers


def test_other_origin_not_allowed(monkeypatch):
    r = _preflight(ALLOWED, "http://evil.example", monkeypatch)

    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("origins", ["", " , "])
def test_no_cors_when_unset(monkeypatch, origins):
    r = _preflight(origins, ALLOWED, monkeypatch)

    assert "access-control-allow-origin" not in r.headers
