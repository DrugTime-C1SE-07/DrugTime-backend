"""Đối chiếu OpenAPI sinh từ app với hợp đồng viết tay api_contract/openapi.json cho /auth/*.

Hợp đồng là nguồn chuẩn (task adhoc-20261002-login-integration). Lệch nhau thì sửa code, hoặc sửa
hợp đồng kèm lý do.
"""

import json
from pathlib import Path

import pytest

from drugtime.main import create_app

CONTRACT = Path(__file__).resolve().parents[3] / "api_contract" / "openapi.json"
OPERATIONS = [
    ("post", "/auth/mobile/otp"),
    ("post", "/auth/mobile/verify"),
    ("post", "/auth/profile"),
    ("post", "/auth/admin/login"),
    ("post", "/auth/admin/session/refresh"),
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
    """Schema sau khi bỏ $ref và nhánh null của anyOf."""
    node = _resolve(spec, node)
    for branch in node.get("anyOf", []):
        if _resolve(spec, branch).get("type") != "null":
            return _object(spec, branch)
    return node


def _shape(spec, node, depth=0):
    """(tên field, field bắt buộc, shape của field con kiểu object)."""
    node = _object(spec, node)
    props = node.get("properties")
    if not props or depth > 3:
        return None
    return (
        sorted(props),
        sorted(node.get("required", [])),
        {k: _shape(spec, v, depth + 1) for k, v in sorted(props.items())},
    )


def _json_schema(op, code=None):
    container = op["requestBody"] if code is None else op["responses"][code]
    return container["content"]["application/json"]["schema"]


@pytest.mark.parametrize("method, path", OPERATIONS)
def test_auth_operations_match_contract(specs, method, path):
    contract, app = specs
    c_op, a_op = contract["paths"][path][method], app["paths"][path][method]

    assert set(c_op["responses"]) == set(a_op["responses"]), path
    assert _shape(contract, _json_schema(c_op)) == _shape(app, _json_schema(a_op)), path
    if "200" in c_op["responses"]:
        assert _shape(contract, _json_schema(c_op, "200")) == _shape(
            app, _json_schema(a_op, "200")
        ), path


@pytest.mark.parametrize("method, path", OPERATIONS)
def test_success_responses_carry_no_supabase_tokens(specs, method, path):
    _, app = specs
    op = app["paths"][path][method]
    if "200" not in op["responses"]:
        return
    shape = repr(_shape(app, _json_schema(op, "200")))

    assert "supabase" not in shape
    assert "refresh_token" not in shape


def test_register_absent_everywhere(specs):
    contract, app = specs

    assert "/auth/register" not in contract["paths"]
    assert "/auth/register" not in app["paths"]
