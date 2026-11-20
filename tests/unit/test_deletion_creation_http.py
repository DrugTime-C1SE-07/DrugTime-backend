import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.consent.adapters.inbound.deletion_http import get_deletion_creation
from drugtime.modules.consent.domain.deletion_creation import PendingDeletion
from drugtime.modules.identity import api as identity
from drugtime.shared.errors import DomainError

BASE = "/data-deletion-requests"


@pytest.fixture
def client():
    app = create_app()
    user = identity.CurrentUser(uuid4(), False)
    service = Mock()
    app.dependency_overrides[identity.current_mobile_user] = lambda: user
    app.dependency_overrides[get_deletion_creation] = lambda: service
    return TestClient(app), user.id, service


def test_otp_endpoint_does_not_accept_an_email_override(client):
    http, uid, service = client
    service.issue.return_value = uuid4(), datetime(2026, 11, 11, tzinfo=UTC)
    for args in ({"json": {"email": "other@example.test"}}, {"params": {"user_id": str(uid)}}):
        response = http.post(BASE + "/otp", **args)
        assert response.status_code == 422
        assert response.headers["Cache-Control"] == "no-store"
    service.issue.assert_not_called()
    response = http.post(BASE + "/otp")
    assert response.status_code == 201
    assert set(response.json()) == {"challenge_id", "expires_at"}
    service.issue.assert_called_once_with(uid)


@pytest.mark.parametrize("created,status", [(True, 201), (False, 200)])
def test_confirm_deletion_returns_saved_deadline(client, created, status):
    http, uid, service = client
    at = datetime(2026, 11, 11, tzinfo=UTC)
    if not created:
        at = at.astimezone(timezone(timedelta(hours=7)))
    challenge = uuid4()
    service.confirm.return_value = PendingDeletion(at, at + timedelta(days=30)), created
    response = http.post(BASE, json={"challenge_id": str(challenge)})
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "status": "cho_xoa",
        "requested_at": "2026-11-11T00:00:00Z",
        "scheduled_deletion_at": "2026-12-11T00:00:00Z",
    }
    service.confirm.assert_called_once_with(uid, challenge)


def test_validation_never_echoes_otp_and_domain_failure_matches_contract(client):
    http, _, service = client
    challenge = str(uuid4())
    invalid = http.post(BASE, json={"challenge_id": challenge, "unexpected": "bad-secret"})
    assert invalid.status_code == 422
    assert "bad-secret" not in invalid.text
    service.confirm.assert_not_called()
    service.confirm.side_effect = DomainError("deletion_otp_invalid")
    response = http.post(BASE, json={"challenge_id": challenge})
    assert response.status_code == 422
    assert response.json() == {"detail": "deletion_otp_invalid"}


def test_openapi_operations_match_the_approved_contract():
    path = Path(__file__).resolve().parents[3] / "api_contract/openapi.json"
    if not path.is_file():
        pytest.skip("API contract checkout is unavailable")
    contract = json.loads(path.read_text(encoding="utf8"))
    generated = create_app().openapi()
    for method, path in (
        ("post", BASE),
        ("post", BASE + "/otp"),
        ("post", BASE + "/otp/verify"),
        ("get", BASE + "/current"),
        ("post", BASE + "/current/cancel"),
    ):
        expected = contract["paths"][path][method]
        actual = generated["paths"][path][method]
        for field in ("operationId", "security"):
            assert actual[field] == expected[field]
        assert actual["responses"].keys() == expected["responses"].keys()


def test_verify_only_and_lookup_do_not_create_or_cancel(client):
    http, uid, service = client
    at = datetime(2026, 11, 19, tzinfo=UTC)
    challenge = uuid4()
    response = http.post(
        BASE + "/otp/verify", json={"challenge_id": str(challenge), "otp": "012345"}
    )
    assert response.status_code == 204 and not response.content
    service.verify.assert_called_once_with(uid, challenge, "012345")
    service.current.return_value = PendingDeletion(at, at + timedelta(days=30))
    for _ in range(2):
        response = http.get(BASE + "/current")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    service.cancel.assert_not_called()
    response = http.post(BASE + "/current/cancel")
    assert response.status_code == 204 and not response.content
    service.cancel.assert_called_once_with(uid)


def test_lookup_cancel_reject_identity_overrides_and_never_cache_errors(client):
    http, _, service = client
    for method, path in ((http.get, "/current"), (http.post, "/current/cancel")):
        response = method(BASE + path, params={"user_id": str(uuid4())})
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"
    service.current.assert_not_called()
    service.cancel.assert_not_called()
