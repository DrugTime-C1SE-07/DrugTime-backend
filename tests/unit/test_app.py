from fastapi.testclient import TestClient

from drugtime.main import create_app


def test_liveness_and_routes_mounted():
    # AC11: App phải mount route /doses/batch cùng các route nền tảng trong OpenAPI runtime.
    client = TestClient(create_app())
    assert client.get("/health/live").json() == {"status": "ok"}
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/auth/register",
        "/auth/mobile/otp",
        "/auth/mobile/verify",
        "/auth/profile",
        "/auth/admin/login",
        "/auth/admin/session/refresh",
        "/doses/batch",
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

