"""Đối chiếu OpenAPI sinh từ app với hợp đồng viết tay cho gợi ý bữa ăn (task 4.26 AC19; 5.11)."""

import json
from pathlib import Path

import pytest

from drugtime.main import create_app

CONTRACT = Path(__file__).resolve().parents[3] / "api_contract" / "openapi.json"
PATH = "/patients/{patient_id}/meal-suggestions"

pytestmark = pytest.mark.skipif(not CONTRACT.exists(), reason="api_contract chưa checkout")


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


def _resolve(spec, node):
    while "$ref" in node:
        ref = node["$ref"]
        parts = ref.split("/")[1:]
        target = spec
        for p in parts:
            target = target[p]
        node = target
    return node


def _object(spec, node):
    node = _resolve(spec, node)
    if "properties" in node or node.get("type") == "array":
        return node
    for key in ("anyOf", "oneOf", "allOf"):
        for branch in node.get(key, []):
            branch = _resolve(spec, branch)
            if branch.get("type") != "null" and ("properties" in branch or "type" in branch):
                return _object(spec, branch)
    return node


def _shape(spec, node, depth=0):
    node = _object(spec, node)
    if node.get("type") == "array":
        return _shape(spec, node["items"], depth)
    props = node.get("properties")
    if not props or depth > 4:
        return None
    return (
        sorted(props),
        sorted(node.get("required", [])),
        {k: _shape(spec, v, depth + 1) for k, v in sorted(props.items())},
    )


def _body(spec, op, code=None):
    target = op["requestBody"] if code is None else _resolve(spec, op["responses"][code])
    return target["content"]["application/json"]["schema"]


def test_operation_matches_contract__AC19(specs):
    contract, app = specs
    c_op, a_op = contract["paths"][PATH]["post"], app["paths"][PATH]["post"]
    assert c_op["operationId"] == a_op["operationId"] == "createMealSuggestions"
    assert set(c_op["responses"]) == {"200", "401", "403", "422", "429", "502", "503"}
    assert set(c_op["responses"]) <= set(a_op["responses"])
    assert _shape(contract, _body(contract, c_op)) == _shape(app, _body(app, a_op))
    assert _shape(contract, _body(contract, c_op, "200")) == _shape(app, _body(app, a_op, "200"))
    for key in ("x-health-scope", "x-health-audit-self"):
        assert c_op[key] == a_op[key]
    assert a_op["security"] == [{"bearerAuth": []}]


def test_request_forbids_unknown_fields(specs):
    _, app = specs
    body = _object(app, _body(app, app["paths"][PATH]["post"]))
    assert body["additionalProperties"] is False
    declaration = _object(app, body["properties"]["allergies"])
    assert declaration["additionalProperties"] is False


@pytest.mark.parametrize(
    "schema,field,bounds",
    [
        ("DietaryDeclaration", "items", {"maxItems": 10}),
        ("MealSuggestionRequest", "preferences", {"maxItems": 5}),
    ],
)
def test_list_bounds_match(specs, schema, field, bounds):
    contract, app = specs
    c = contract["components"]["schemas"][schema]["properties"][field]
    a = _object(app, app["components"]["schemas"][schema]["properties"][field])
    for k, v in bounds.items():
        assert c[k] == a[k] == v
    assert c["items"]["maxLength"] == a["items"]["maxLength"] == 40


# --- Task 5.11: ảnh món ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "operation", "codes"),
    [
        ("/meal-images", "listMealImageStatuses", {"200", "401", "422", "503"}),
        ("/meal-images/{image_id}", "getMealImage", {"200", "401", "404", "422", "503"}),
    ],
)
def test_image_operations_match_contract(specs, path, operation, codes):
    contract, app = specs
    c_op, a_op = contract["paths"][path]["get"], app["paths"][path]["get"]
    assert c_op["operationId"] == a_op["operationId"] == operation
    assert set(c_op["responses"]) == codes
    assert set(c_op["responses"]) <= set(a_op["responses"])
    assert a_op["security"] == [{"bearerAuth": []}]
    assert "x-health-scope" not in c_op and "x-health-scope" not in a_op


def test_image_list_shape_matches(specs):
    contract, app = specs
    c_op, a_op = contract["paths"]["/meal-images"]["get"], app["paths"]["/meal-images"]["get"]
    assert _shape(contract, _body(contract, c_op, "200")) == _shape(app, _body(app, a_op, "200"))
    c_ids = next(p for p in c_op["parameters"] if p["name"] == "ids")["schema"]
    a_ids = next(p for p in a_op["parameters"] if p["name"] == "ids")["schema"]
    bounds = (a_ids["minItems"], a_ids["maxItems"])
    assert (c_ids["minItems"], c_ids["maxItems"]) == bounds == (1, 20)


def test_image_content_types_match(specs):
    contract, app = specs
    c = contract["paths"]["/meal-images/{image_id}"]["get"]["responses"]["200"]["content"]
    a = app["paths"]["/meal-images/{image_id}"]["get"]["responses"]["200"]["content"]
    assert set(c) == {"image/jpeg", "image/png", "image/webp"} <= set(a)
