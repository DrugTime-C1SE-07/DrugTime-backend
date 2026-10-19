"""Đối chiếu OpenAPI sinh từ app với hợp đồng api_contract/openapi.json cho /family (task 3.10).

Hợp đồng là nguồn chuẩn. Lệch nhau thì sửa code, hoặc sửa hợp đồng kèm lý do.
"""

import json

import pytest
from pydantic import ValidationError

from drugtime.main import create_app
from drugtime.modules.family.adapters.inbound.schemas import LinkRequestCreate
from tests.unit.test_contract_medication import CONTRACT, _object, _request, _response, _shape

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


# --- task 3.13: POST /family/link-requests, 403 mới của GET /family/link-code -------------

REQUESTS = "/family/link-requests"


def test_create_link_request_matches_contract__AC21(specs):
    contract, app = specs
    c_op, a_op = contract["paths"][REQUESTS]["post"], app["paths"][REQUESTS]["post"]

    assert c_op["operationId"] == a_op["operationId"] == "createLinkRequest"
    assert set(c_op["responses"]) == set(a_op["responses"]) - {"default"}
    # Không có tham số nào ngoài header Authorization (không có X-Device-Id).
    assert "parameters" not in c_op
    assert [(p["name"], p["in"]) for p in a_op.get("parameters", [])] == [
        ("authorization", "header")
    ]
    assert _shape(contract, _request(contract, c_op)) == _shape(app, _request(app, a_op))
    for code in ("200", "201"):
        assert _shape(contract, _response(contract, c_op, code)) == _shape(
            app, _response(app, a_op, code)
        ), code
    assert "Retry-After" in a_op["responses"]["429"]["headers"]


def test_link_request_schemas_match_contract__AC21(specs):
    contract, app = specs
    c_op, a_op = contract["paths"][REQUESTS]["post"], app["paths"][REQUESTS]["post"]
    c_body, a_body = _object(contract, _request(contract, c_op)), _object(app, _request(app, a_op))
    c_resp = _object(contract, _response(contract, c_op, "201"))
    a_resp = _object(app, _response(app, a_op, "201"))

    for c_schema, a_schema in ((c_body, a_body), (c_resp, a_resp)):
        assert c_schema["additionalProperties"] is False
        assert a_schema.get("additionalProperties") is False
    for field in ("client_uuid", "code"):
        c_field, a_field = c_body["properties"][field], a_body["properties"][field]
        keys = ("type", "format", *BOUNDS)
        assert {k: c_field.get(k) for k in keys} == {k: a_field.get(k) for k in keys}, field
    c_status = _object(contract, c_resp["properties"]["status"])
    assert c_status["enum"] == a_resp["properties"]["status"]["enum"]
    assert c_resp["properties"]["id"]["format"] == a_resp["properties"]["id"]["format"] == "int64"
    assert a_resp["properties"]["requested_at"]["format"] == "date-time"


def test_link_code_403_documented__AC32(specs):
    contract, app = specs
    c_403 = contract["components"]["responses"]["LinkCodeForbidden"]
    details = {
        e["value"]["detail"] for e in c_403["content"]["application/json"]["examples"].values()
    }
    a_403 = app["paths"][PATH]["get"]["responses"]["403"]["description"]

    assert details == {"khong_co_quyen", "family_sharing_consent_required"}
    assert all(d in a_403 for d in details)


def test_request_body_normalizes_code__AC20():
    key = "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58"

    body = LinkRequestCreate.model_validate({"client_uuid": key, "code": " k7m2q9xar4 "})

    assert body.code == "K7M2Q9XAR4"


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "K7M2Q9XAR4"},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58"},
        {"client_uuid": "not-a-uuid", "code": "K7M2Q9XAR4"},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58", "code": ""},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58", "code": "X" * 33},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58", "code": 1234567890},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58", "code": "K7M2Q9XAR"},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58", "code": "K7M2Q9XAR0"},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58", "code": "K7M2Q9XAOI"},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58", "code": "K7M2Q9XAL1"},
        {"client_uuid": "9b2e4c71-5d3a-4f8e-a1c6-7e0d2b9f4a58", "code": "K7M2Q9XAR4", "x": 1},
    ],
)
def test_request_body_rejects_invalid__AC20(payload):
    with pytest.raises(ValidationError) as exc:
        LinkRequestCreate.model_validate(payload)

    # Message lỗi do server viết không lặp lại mã (QD-04).
    assert "K7M2Q9XA" not in " ".join(e["msg"] for e in exc.value.errors())
