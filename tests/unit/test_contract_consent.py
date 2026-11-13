"""Đối chiếu OpenAPI sinh từ app với hợp đồng api_contract/openapi.json cho /consents (task 1.14).

Hợp đồng là nguồn chuẩn. Lệch nhau thì sửa code, hoặc sửa hợp đồng kèm lý do.
"""

import json

import pytest

from drugtime.main import create_app
from tests.unit.test_contract_medication import (
    CONTRACT,
    _object,
    _query_params,
    _request,
    _response,
    _shape,
)

OPERATIONS = [
    ("get", "/consents"),
    ("post", "/consents"),
    ("post", "/consents/{purpose}/withdraw"),
]
PURPOSES = ["health_data", "family_sharing", "ai_meal", "terms"]

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


def test_pending_deletion_queue_matches_contract(specs):
    contract, app = specs
    path = "/admin/deletion-requests"
    c_op, a_op = (spec["paths"][path]["get"] for spec in specs)

    assert c_op["operationId"] == a_op["operationId"]
    assert c_op["security"] == a_op["security"]
    assert _query_params(c_op) == _query_params(a_op)
    assert "requestBody" not in a_op
    assert set(c_op["responses"]) == set(a_op["responses"])
    assert c_op["responses"]["200"]["headers"] == a_op["responses"]["200"]["headers"]

    c_page = _object(contract, _response(contract, c_op, "200"))
    a_page = _object(app, _response(app, a_op, "200"))
    c_item = _object(contract, c_page["properties"]["items"]["items"])
    a_item = _object(app, a_page["properties"]["items"]["items"])
    for expected, actual in ((c_page, a_page), (c_item, a_item)):
        assert set(expected["required"]) == set(actual["required"])
        assert expected["additionalProperties"] == actual["additionalProperties"]
        for name, field in expected["properties"].items():
            for constraint in ("type", "format", "minimum", "maxItems", "const"):
                assert field.get(constraint) == actual["properties"][name].get(constraint)


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


def test_withdraw_declares_422_for_not_withdrawable(specs):
    contract, app = specs
    c_422 = contract["paths"]["/consents/{purpose}/withdraw"]["post"]["responses"]["422"]
    a_422 = app["paths"]["/consents/{purpose}/withdraw"]["post"]["responses"]["422"]
    assert c_422["content"]["application/json"]["examples"]["not_withdrawable"]["value"] == {
        "detail": "consent_not_withdrawable"
    }
    assert "consent_not_withdrawable" in a_422["description"]


def test_consent_list_has_one_item_per_purpose(specs):
    contract, _ = specs
    items = contract["components"]["schemas"]["ConsentList"]["properties"]["items"]
    assert items["minItems"] == items["maxItems"] == len(PURPOSES)
