"""Handler 429 gắn header Retry-After khi lỗi mang thời gian chờ (task 3.13, Q5)."""

from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.shared.errors import TooManyRequests


def _client():
    app = create_app()

    @app.get("/_test/locked")
    def _locked():
        raise TooManyRequests("link_request_locked", retry_after=540)

    @app.get("/_test/rate-limited")
    def _rate_limited():
        raise TooManyRequests("rate_limited")

    return TestClient(app)


def test_429_with_retry_after_sets_header__AC10():
    r = _client().get("/_test/locked")

    assert (r.status_code, r.json()) == (429, {"detail": "link_request_locked"})
    assert r.headers["retry-after"] == "540"


def test_429_without_retry_after_has_no_header():
    r = _client().get("/_test/rate-limited")

    assert (r.status_code, r.json()) == (429, {"detail": "rate_limited"})
    assert "retry-after" not in r.headers


def test_retry_after_attribute_defaults_to_none():
    assert TooManyRequests("rate_limited").retry_after is None
    assert str(TooManyRequests("link_request_cooldown", retry_after=60)) == "link_request_cooldown"
