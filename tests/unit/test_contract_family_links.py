import json

import pytest

from drugtime.main import create_app
from tests.unit.test_contract_medication import CONTRACT, _resolve, _response, _shape

OPERATIONS = [
    ("get", "/family/links", "listPendingFamilyLinks"),
    ("post", "/family/links/{link_id}/approve", "approveFamilyLink"),
    ("post", "/family/links/{link_id}/reject", "rejectFamilyLink"),
]
SCHEMAS = [
    "PendingFamilyLink",
    "PendingFamilyLinkList",
    "FamilyLinkApprovalRequest",
    "FamilyLinkConsentConfirmation",
    "FamilyLinkApproval",
    "FamilyLinkRejection",
]


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


def canonical(spec, schema):
    schema = _resolve(spec, schema)
    result = {
        k: schema[k]
        for k in ("type", "format", "minimum", "minLength", "maxLength", "additionalProperties")
        if k in schema
    }
    if "const" in schema or "enum" in schema:
        result["enum"] = schema.get("enum", [schema.get("const")])
    for key in ("anyOf", "oneOf"):
        if key in schema:
            result[key] = [canonical(spec, branch) for branch in schema[key]]
    if "properties" in schema:
        result["properties"] = {k: canonical(spec, v) for k, v in schema["properties"].items()}
        result["required"] = sorted(schema.get("required", []))
    if "items" in schema:
        result["items"] = canonical(spec, schema["items"])
    return result


@pytest.mark.parametrize("name", SCHEMAS)
def test_six_schemas_match_contract_types_required_nullability_and_constraints(specs, name):
    contract, app = specs
    assert canonical(contract, contract["components"]["schemas"][name]) == canonical(
        app, app["components"]["schemas"][name]
    )


@pytest.mark.parametrize("method,path,operation", OPERATIONS)
def test_three_operations_match_contract(specs, method, path, operation):
    contract, app = specs
    c, a = contract["paths"][path][method], app["paths"][path][method]
    assert c["operationId"] == a["operationId"] == operation
    assert set(c["responses"]) == set(a["responses"])
    assert _shape(contract, _response(contract, c, "200")) == _shape(app, _response(app, a, "200"))
    assert ("requestBody" in c) is ("requestBody" in a)
    cp = [p for p in c.get("parameters", []) if p["in"] != "header"]
    ap = [p for p in a.get("parameters", []) if p["in"] != "header"]
    assert {(p["name"], p["in"], p["required"]) for p in cp} == {
        (p["name"], p["in"], p["required"]) for p in ap
    }
    for cparam in cp:
        aparam = next(p for p in ap if p["name"] == cparam["name"])
        assert canonical(contract, cparam["schema"]) == canonical(app, aparam["schema"])
    if method == "post" and path.endswith("approve"):
        assert a["requestBody"]["required"] is True
        assert canonical(
            contract, c["requestBody"]["content"]["application/json"]["schema"]
        ) == canonical(app, a["requestBody"]["content"]["application/json"]["schema"])
        assert len(_response(app, a, "422")["oneOf"]) == 2


def test_all_generated_schema_refs_resolve(specs):
    _, app = specs

    def visit(node):
        if isinstance(node, dict):
            if "$ref" in node:
                _resolve(app, node)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(app)
