"""Đối chiếu OpenAPI sinh từ app với hợp đồng viết tay api_contract/openapi.json (task 2.01).

Hợp đồng là nguồn chuẩn. Lệch nhau thì sửa code, hoặc sửa hợp đồng kèm lý do.
"""

import json
from pathlib import Path

import pytest

from drugtime.main import create_app

CONTRACT = Path(__file__).resolve().parents[3] / "api_contract" / "openapi.json"
OPERATIONS = [
    ("get", "/medications"),
    ("post", "/medications"),
    ("get", "/medications/{id}"),
    ("patch", "/medications/{id}"),
    ("delete", "/medications/{id}"),
    ("get", "/catalog/medications"),
]

pytestmark = pytest.mark.skipif(not CONTRACT.exists(), reason="api_contract chưa checkout")


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


def _resolve(spec, node):
    while "$ref" in node:
        name = node["$ref"].split("/")[-1]
        node = spec["components"]["schemas"][name]
    return node


def _object(spec, node):
    """Schema object sau khi bỏ $ref và nhánh null của anyOf."""
    node = _resolve(spec, node)
    for branch in node.get("anyOf", []):
        if branch.get("type") != "null":
            return _object(spec, branch)
    return node


def _shape(spec, node, depth=0):
    """(tên field, field bắt buộc, shape của field con kiểu object/array object)."""
    node = _object(spec, node)
    if node.get("type") == "array":
        return _shape(spec, node["items"], depth)
    props = node.get("properties")
    if not props or depth > 3:
        return None
    return (
        sorted(props),
        sorted(node.get("required", [])),
        {k: _shape(spec, v, depth + 1) for k, v in sorted(props.items())},
    )


def _request(spec, op):
    return op["requestBody"]["content"]["application/json"]["schema"]


def _response(spec, op, code):
    return op["responses"][code]["content"]["application/json"]["schema"]


@pytest.mark.parametrize("method, path", OPERATIONS)
def test_operations_match_contract(specs, method, path):
    contract, app = specs
    c_op, a_op = contract["paths"][path][method], app["paths"][path][method]

    assert set(c_op["responses"]) <= set(a_op["responses"]), path
    if "requestBody" in c_op:
        assert _shape(contract, _request(contract, c_op)) == _shape(app, _request(app, a_op))
    for code in ("200", "201"):
        if code in c_op["responses"]:
            assert _shape(contract, _response(contract, c_op, code)) == _shape(
                app, _response(app, a_op, code)
            ), (method, path, code)


def test_request_bodies_forbid_unknown_fields(specs):
    _, app = specs
    for method, path in OPERATIONS:
        op = app["paths"][path][method]
        if "requestBody" in op:
            assert _object(app, _request(app, op)).get("additionalProperties") is False


def _query_params(op):
    return {
        p["name"]: (p.get("required", False), {k: p["schema"].get(k) for k in BOUNDS})
        for p in op.get("parameters", [])
        if p["in"] == "query"
    }


BOUNDS = ("minLength", "maxLength", "pattern", "minimum", "maximum", "default")


def test_catalog_search_query_params_match_contract(specs):
    contract, app = specs
    path = "/catalog/medications"
    assert _query_params(contract["paths"][path]["get"]) == _query_params(app["paths"][path]["get"])
