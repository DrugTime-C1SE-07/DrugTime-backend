"""Đối chiếu OpenAPI sinh từ app với hợp đồng viết tay cho gợi ý bữa ăn (task 4.26, AC19)."""

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
    assert set(c_op["responses"]) == {"200", "401", "403", "422", "502", "503"}
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
