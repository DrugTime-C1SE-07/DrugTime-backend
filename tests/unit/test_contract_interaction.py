"""Đối chiếu OpenAPI sinh từ app với hợp đồng viết tay cho danh mục quy tắc tương tác (task 2.16).

Hợp đồng là nguồn chuẩn. So: operationId, mã trạng thái của contract có trong app, shape request
và response 200/201 (tên field, field bắt buộc, lồng nhau), ràng buộc của tham số query.
"""

import json
from pathlib import Path

import pytest

from drugtime.main import create_app

CONTRACT = Path(__file__).resolve().parents[3] / "api_contract" / "openapi.json"
OPERATIONS = [
    ("post", "/admin/drug-interactions"),
    ("get", "/admin/drug-interactions"),
    ("get", "/admin/drug-interactions/{id}"),
    ("patch", "/admin/drug-interactions/{id}"),
    ("delete", "/admin/drug-interactions/{id}"),
    ("get", "/admin/drug-interactions/{id}/versions"),
    ("get", "/admin/drug-interaction-versions/{version_id}"),
    ("post", "/admin/drug-food-interactions"),
    ("get", "/admin/drug-food-interactions"),
    ("get", "/admin/drug-food-interactions/{id}"),
    ("patch", "/admin/drug-food-interactions/{id}"),
    ("delete", "/admin/drug-food-interactions/{id}"),
    ("get", "/admin/drug-food-interactions/{id}/versions"),
    ("get", "/admin/drug-food-interaction-versions/{version_id}"),
    ("get", "/admin/active-ingredients"),
]

pytestmark = pytest.mark.skipif(not CONTRACT.exists(), reason="api_contract chưa checkout")


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


def _resolve(spec, node):
    while "$ref" in node:
        node = spec["components"]["schemas"][node["$ref"].split("/")[-1]]
    return node


def _object(spec, node):
    """Schema sau khi bỏ $ref và nhánh null của anyOf/oneOf. Node đã có `properties` thì giữ
    nguyên (anyOf/oneOf lúc đó chỉ là ràng buộc `required`, không phải kiểu)."""
    node = _resolve(spec, node)
    if "properties" in node or node.get("type") == "array":
        return node
    for key in ("anyOf", "oneOf"):
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
    if not props or depth > 3:
        return None
    return (
        sorted(props),
        sorted(node.get("required", [])),
        {k: _shape(spec, v, depth + 1) for k, v in sorted(props.items())},
    )


def _body(op, code=None):
    target = op["requestBody"] if code is None else op["responses"][code]
    return target["content"]["application/json"]["schema"]


@pytest.mark.parametrize("method, path", OPERATIONS)
def test_operation_matches_contract(specs, method, path):
    contract, app = specs
    c_op, a_op = contract["paths"][path][method], app["paths"][path][method]

    assert c_op["operationId"] == a_op["operationId"]
    assert set(c_op["responses"]) <= set(a_op["responses"]), (method, path)
    if "requestBody" in c_op:
        assert _shape(contract, _body(c_op)) == _shape(app, _body(a_op)), (method, path)
    for code in ("200", "201"):
        if code in c_op["responses"]:
            assert _shape(contract, _body(c_op, code)) == _shape(app, _body(a_op, code)), (
                method,
                path,
                code,
            )
    if "204" in c_op["responses"]:
        assert "content" not in a_op["responses"]["204"]


def test_request_bodies_forbid_unknown_fields(specs):
    _, app = specs
    for method, path in OPERATIONS:
        op = app["paths"][path][method]
        if "requestBody" in op:
            assert _object(app, _body(op)).get("additionalProperties") is False, (method, path)


BOUNDS = ("minLength", "maxLength", "minimum", "maximum", "default", "enum")


def _query_params(spec, op):
    out = {}
    for p in op.get("parameters", []):
        if p["in"] != "query":
            continue
        schema = _object(spec, p["schema"])
        out[p["name"]] = (p.get("required", False), {k: schema.get(k) for k in BOUNDS})
    return out


@pytest.mark.parametrize("method, path", [op for op in OPERATIONS if op[0] in ("get", "delete")])
def test_query_params_match_contract(specs, method, path):
    contract, app = specs
    c_op, a_op = contract["paths"][path][method], app["paths"][path][method]
    assert _query_params(contract, c_op) == _query_params(app, a_op)


def test_severity_scale_documented(specs):
    contract, _ = specs
    severity = contract["components"]["schemas"]["InteractionSeverity"]
    assert (severity["minimum"], severity["maximum"]) == (1, 4)
    for label in (
        "cần theo dõi",
        "cần thận trọng",
        "cân nhắc lợi ích/nguy cơ",
        "phối hợp nguy hiểm",
    ):
        assert label in severity["description"]
