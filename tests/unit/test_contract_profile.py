import json
from pathlib import Path

import pytest

from drugtime.main import create_app

CONTRACT = Path(__file__).resolve().parents[3] / "api_contract" / "openapi.json"
OPERATIONS = [
    ("/profile", "get", 200),
    ("/profile", "put", 204),
    ("/conditions", "get", 200),
    ("/profile/conditions", "post", 201),
    ("/profile/conditions/{id}", "patch", 200),
    ("/profile/conditions/{id}", "delete", 204),
]


@pytest.mark.parametrize("path,method,success", OPERATIONS)
def test_profile_operation_inventory_matches_contract(path, method, success):
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    actual = create_app().openapi()["paths"][path][method]
    expected = contract["paths"][path][method]
    assert actual["operationId"] == expected["operationId"]
    assert str(success) in actual["responses"]
    assert {"401", "422", "500"} <= actual["responses"].keys()
    if path != "/conditions":
        assert "403" in actual["responses"]
    if success == 204:
        assert "content" not in actual["responses"]["204"]


def test_request_schema_required_and_forbidden_fields():
    schemas = create_app().openapi()["components"]["schemas"]
    profile = schemas["ProfileUpdateRequest"]
    assert set(profile["required"]) == {"full_name", "date_of_birth", "gender"}
    for name in (
        "ProfileUpdateRequest",
        "UserConditionCreateRequest",
        "UserConditionUpdateRequest",
    ):
        assert schemas[name]["additionalProperties"] is False
    patch = schemas["UserConditionUpdateRequest"]
    assert set(patch["properties"]) == {"subtype", "stage"}


def _resolve(spec, node):
    while "$ref" in node:
        path = node["$ref"].removeprefix("#/").split("/")
        node = spec
        for part in path:
            node = node[part]
    return node


def _shape(spec, node):
    node = _resolve(spec, node)
    if isinstance(node.get("type"), list):
        return sorted([_shape(spec, {**node, "type": kind}) for kind in node["type"]], key=repr)
    if "anyOf" in node:
        return sorted([_shape(spec, branch) for branch in node["anyOf"]], key=repr)
    result = {
        key: node[key]
        for key in (
            "type",
            "format",
            "minimum",
            "maximum",
            "minLength",
            "minProperties",
            "pattern",
            "additionalProperties",
        )
        if key in node
    }
    # FastAPI's OpenAPI model converts numeric bounds to floats; runtime stays strict int64.
    for key in ("minimum", "maximum"):
        if key in result:
            result[key] = float(result[key])
    if "enum" in node:
        result["enum"] = sorted(node["enum"])
    if "properties" in node:
        result["required"] = sorted(node.get("required", []))
        result["properties"] = {
            key: _shape(spec, value) for key, value in node["properties"].items()
        }
    if "items" in node:
        result["items"] = _shape(spec, node["items"])
    return result


@pytest.mark.parametrize("path,method,success", OPERATIONS)
def test_request_and_success_response_shapes_match_contract(path, method, success):
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    runtime = create_app().openapi()
    expected, actual = contract["paths"][path][method], runtime["paths"][path][method]
    assert actual["security"] == expected["security"]
    runtime_bearer = runtime["components"]["securitySchemes"]["bearerAuth"]
    contract_bearer = contract["components"]["securitySchemes"]["bearerAuth"]
    for field in ("type", "scheme", "bearerFormat"):
        assert runtime_bearer[field] == contract_bearer[field]
    if "requestBody" in expected:
        assert _shape(
            contract, expected["requestBody"]["content"]["application/json"]["schema"]
        ) == (_shape(runtime, actual["requestBody"]["content"]["application/json"]["schema"]))
    if success != 204:
        e = _resolve(contract, expected["responses"][str(success)])
        a = _resolve(runtime, actual["responses"][str(success)])
        assert _shape(contract, e["content"]["application/json"]["schema"]) == (
            _shape(runtime, a["content"]["application/json"]["schema"])
        )
        if path != "/conditions":
            assert (
                a["headers"]["Cache-Control"]["schema"] == (e["headers"]["Cache-Control"]["schema"])
            )
