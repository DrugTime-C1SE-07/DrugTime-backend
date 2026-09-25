from fastapi.testclient import TestClient

from drugtime.main import create_app


def test_liveness_and_routes_mounted():
    client = TestClient(create_app())
    assert client.get("/health/live").json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/auth/register",
        "/auth/mobile/otp",
        "/auth/mobile/verify",
        "/auth/admin/login",
        "/auth/admin/session/refresh",
        "/auth/otp",
        "/auth/verify",
        "/doses/batch",
    } <= set(paths)
