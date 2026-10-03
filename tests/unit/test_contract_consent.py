"""Đối chiếu OpenAPI sinh từ app với hợp đồng api_contract/openapi.json cho /consents (task 1.14).

Hợp đồng là nguồn chuẩn. Lệch nhau thì sửa code, hoặc sửa hợp đồng kèm lý do.
"""

import json

import pytest

from drugtime.main import create_app
from tests.unit.test_contract_medication import CONTRACT, _object, _request, _response, _shape

OPERATIONS = [
    ("get", "/consents"),
    ("post", "/consents"),
    ("post", "/consents/{purpose}/withdraw"),
]
PURPOSES = ["health_data", "family_sharing", "ai_meal"]

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


def test_grant_body_forbids_unknown_fields_and_bounds_version(specs):
    _, app = specs
    body = _object(app, _request(app, app["paths"]["/consents"]["post"]))
    assert body.get("additionalProperties") is False
    version = body["properties"]["document_version"]
    assert (version["minLength"], version["maxLength"]) == (1, 64)


def test_purpose_and_status_enums_match_contract(specs):
    contract, app = specs
    assert contract["components"]["schemas"]["ConsentPurpose"]["enum"] == PURPOSES
    assert app["components"]["schemas"]["Purpose"]["enum"] == PURPOSES
    path_param = app["paths"]["/consents/{purpose}/withdraw"]["post"]["parameters"][0]
    assert (path_param["name"], path_param["in"], path_param["required"]) == (
        "purpose",
        "path",
        True,
    )
    status = _object(app, app["components"]["schemas"]["Consent"]["properties"]["status"])
    assert status["enum"] == contract["components"]["schemas"]["ConsentStatus"]["enum"]
