from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.shared.errors import ServiceUnavailable, TooManyRequests


def test_liveness_and_routes_mounted():
    client = TestClient(create_app())
    assert client.get("/health/live").json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/auth/mobile/otp",
        "/auth/mobile/verify",
        "/auth/profile",
        "/auth/admin/login",
        "/auth/admin/session/refresh",
        "/doses/batch",
        "/medications",
        "/medications/{id}",
    } <= set(paths)
    assert {"post"} <= set(paths["/medications"])
    assert {"get", "patch"} <= set(paths["/medications/{id}"])


def test_register_route_removed():
    client = TestClient(create_app())

    assert "/auth/register" not in client.get("/openapi.json").json()["paths"]
    r = client.post(
        "/auth/register",
        json={
            "email": "lan@example.com",
            "ho_ten": "Nguyễn Thị Lan",
            "so_dien_thoai": "0912345678",
            "ngay_sinh": "1958-04-12",
            "gioi_tinh": "nu",
        },
    )
    assert r.status_code in (404, 405)


def test_rate_limit_and_unavailable_map_to_429_and_503():
    app = create_app()

    @app.get("/_test/rate-limited")
    def _rate_limited():
        raise TooManyRequests("rate_limited")

    @app.get("/_test/unavailable")
    def _unavailable():
        raise ServiceUnavailable("auth_provider_unavailable")

    client = TestClient(app)
    r = client.get("/_test/rate-limited")
    assert (r.status_code, r.json()) == (429, {"detail": "rate_limited"})
    r = client.get("/_test/unavailable")
    assert (r.status_code, r.json()) == (503, {"detail": "auth_provider_unavailable"})
