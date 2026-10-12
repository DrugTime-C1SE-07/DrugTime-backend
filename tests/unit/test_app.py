from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.shared.errors import Conflict, ServiceUnavailable, TooManyRequests


def test_liveness_and_routes_mounted():
    # AC11: App phải mount route /doses/batch cùng các route nền tảng trong OpenAPI runtime.
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


def test_doses_batch_openapi_uses_contract_shape():
    # AC10/AC11: Contract runtime dùng schedule_id integer và response 200 body {items, summary}.
    client = TestClient(create_app())
    operation = client.get("/openapi.json").json()["paths"]["/doses/batch"]["post"]

    assert "204" not in operation["responses"]
    assert "200" in operation["responses"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["items"]["$ref"].endswith("DoseConfirmationIn")

    components = client.get("/openapi.json").json()["components"]["schemas"]
    request_item = components["DoseConfirmationIn"]
    assert request_item["properties"]["schedule_id"]["type"] == "integer"

    response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    response_schema_name = response_ref.rsplit("/", maxsplit=1)[-1]
    response_schema = components[response_schema_name]
    assert {"items", "summary"} <= set(response_schema["properties"])

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


def test_conflict_maps_to_409():
    app = create_app()

    @app.get("/_test/conflict")
    def _conflict():
        raise Conflict("version_conflict")

    r = TestClient(app).get("/_test/conflict")
    assert (r.status_code, r.json()) == (409, {"detail": "version_conflict"})
