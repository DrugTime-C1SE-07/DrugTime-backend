"""Đối chiếu OpenAPI sinh từ app với hợp đồng api_contract/openapi.json cho /family (task 3.10).

Hợp đồng là nguồn chuẩn. Lệch nhau thì sửa code, hoặc sửa hợp đồng kèm lý do.
"""

import json

import pytest

from drugtime.main import create_app
from tests.unit.test_contract_medication import CONTRACT, _object, _response, _shape

PATH = "/family/link-code"
BOUNDS = ("pattern", "minLength", "maxLength")

pytestmark = pytest.mark.skipif(not CONTRACT.exists(), reason="api_contract chưa checkout")


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


def test_operation_matches_contract__AC15(specs):
    contract, app = specs
    c_op, a_op = contract["paths"][PATH]["get"], app["paths"][PATH]["get"]

    assert c_op["operationId"] == a_op["operationId"] == "getMyLinkCode"
    assert set(c_op["responses"]) <= set(a_op["responses"])
    # Không có input nào ngoài header Authorization (do identity.current_user khai báo).
    assert "requestBody" not in a_op
    assert [p["in"] for p in a_op.get("parameters", [])] == ["header"]
    assert _shape(contract, _response(contract, c_op, "200")) == _shape(
        app, _response(app, a_op, "200")
    )


def test_link_code_constraints_match_contract__AC15(specs):
    contract, app = specs
    c_schema = _object(contract, _response(contract, contract["paths"][PATH]["get"], "200"))
    a_schema = _object(app, _response(app, app["paths"][PATH]["get"], "200"))

    assert c_schema["additionalProperties"] is False
    assert a_schema.get("additionalProperties") is False
    for field in ("code", "qr_payload"):
        c_field, a_field = c_schema["properties"][field], a_schema["properties"][field]
        assert {k: c_field.get(k) for k in BOUNDS} == {k: a_field.get(k) for k in BOUNDS}, field
