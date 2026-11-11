import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.modules.identity.adapters.inbound.email_change_http import get_email_change
from drugtime.shared.errors import DomainError


def test_email_change_http_enforces_shape_no_store_and_no_sensitive_echo():
    app = create_app()
    service = Mock()
    uid, challenge = uuid4(), uuid4()
    app.dependency_overrides[identity.current_mobile_user] = lambda: identity.CurrentUser(
        uid, False
    )
    app.dependency_overrides[get_email_change] = lambda: service
    client = TestClient(app)
    service.start.return_value = challenge, datetime(2026, 11, 11, tzinfo=UTC)
    r = client.post("/me/email-change/otp", json={"new_email": "new@example.test"})
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    service.start.assert_called_once_with(uid, "new@example.test")
    r = client.post(
        "/me/email-change/verify-current",
        json={"challenge_id": str(challenge), "otp": "secret-value"},
    )
    assert r.status_code == 422 and "secret-value" not in r.text
    service.confirm.side_effect = DomainError("email_change_otp_invalid")
    r = client.post(
        "/me/email-change/confirm", json={"challenge_id": str(challenge), "otp": "123456"}
    )
    assert r.status_code == 422 and r.json() == {"detail": "email_change_otp_invalid"}
    r = client.post("/me/email-change/otp?user_id=other", json={"new_email": "x@example.test"})
    assert r.status_code == 422


def test_email_change_operations_exist_in_approved_contract():
    path = Path(__file__).resolve().parents[3] / "api_contract/openapi.json"
    contract = json.loads(path.read_text(encoding="utf8"))
    generated = create_app().openapi()
    for suffix in ("otp", "verify-current", "confirm"):
        path = f"/me/email-change/{suffix}"
        expected = contract["paths"][path]["post"]
        actual = generated["paths"][path]["post"]
        assert actual["operationId"] == expected["operationId"]
        assert actual["security"] == expected["security"]
        assert actual["responses"].keys() == expected["responses"].keys()
        variants = actual["responses"]["422"]["content"]["application/json"]["schema"]["anyOf"]
        detail_types = {
            generated["components"]["schemas"][variant["$ref"].split("/")[-1]]
            .get("properties", {}).get("detail", {}).get("type")
            for variant in variants
        }
        assert detail_types == {"array", "string"}
