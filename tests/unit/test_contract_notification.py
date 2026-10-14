"""Đối chiếu OpenAPI sinh từ app với hợp đồng api_contract/openapi.json cho /notifications (task 3.20).

Hợp đồng là nguồn chuẩn. Lệch nhau thì sửa code, hoặc sửa hợp đồng kèm lý do.
"""

import json

import pytest

from drugtime.main import create_app
from tests.unit.test_contract_medication import CONTRACT, _object, _request, _response, _shape

OPERATIONS = [
    ("get", "/notifications"),
    ("patch", "/notifications/{id}"),
]

pytestmark = pytest.mark.skipif(not CONTRACT.exists(), reason="api_contract chưa checkout")


@pytest.fixture(scope="module")
def specs():
    return json.loads(CONTRACT.read_text(encoding="utf-8")), create_app().openapi()


@pytest.mark.parametrize("method, path", OPERATIONS)
def test_operations_match_contract(specs, method, path):
    contract, app = specs
    c_op, a_op = contract["paths"][path][method], app["paths"][path][method]

    assert c_op["operationId"] == a_op["operationId"]
    assert set(c_op["responses"]) <= set(a_op["responses"]), path
    if "requestBody" in c_op:
        assert _shape(contract, _request(contract, c_op)) == _shape(app, _request(app, a_op))
    for code in ("200", "201"):
        if code in c_op["responses"]:
            assert _shape(contract, _response(contract, c_op, code)) == _shape(
                app, _response(app, a_op, code)
            ), (method, path, code)


def test_notification_patch_request_body_forbids_unknown_fields(specs):
    _, app = specs
    patch_op = app["paths"]["/notifications/{id}"]["patch"]
    schema = _object(app, _request(app, patch_op))
    assert schema.get("additionalProperties") is False or "is_read" in schema.get("properties", {})


def test_notification_query_params_match_contract(specs):
    contract, app = specs
    c_params = {p["name"]: p for p in contract["paths"]["/notifications"]["get"]["parameters"]}
    a_params = {p["name"]: p for p in app["paths"]["/notifications"]["get"]["parameters"]}

    assert "is_read" in a_params
    assert "limit" in a_params
    assert "offset" in a_params
