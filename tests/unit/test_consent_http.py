"""Lớp HTTP của /consents không cần DB: 401 khi thiếu token, 422 khi sai cấu trúc."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow

VALID = {"purpose": "health_data", "document_version": "2026-10-v1"}


def _fake_uow():
    yield object()


@pytest.fixture
def anonymous():
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    return TestClient(app)


@pytest.fixture
def signed_in():
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )
    return TestClient(app)


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/consents", None),
        ("post", "/consents", VALID),
        ("post", "/consents", {"purpose": "all"}),  # body sai vẫn 401
        ("post", "/consents/health_data/withdraw", None),
    ],
)
def test_missing_authorization_401(anonymous, method, path, body):
    r = anonymous.request(method, path, json=body)
    assert r.status_code == 401
    assert r.json() == {"detail": "Missing bearer token"}


@pytest.mark.parametrize(
    "body, loc",
    [
        ({"purpose": "all", "document_version": "2026-10-v1"}, ["body", "purpose"]),
        (
            {"purpose": ["health_data", "ai_meal"], "document_version": "2026-10-v1"},
            ["body", "purpose"],
        ),
        ({"document_version": "2026-10-v1"}, ["body", "purpose"]),
        ({"purpose": "health_data"}, ["body", "document_version"]),
        ({"purpose": "health_data", "document_version": ""}, ["body", "document_version"]),
        ({**VALID, "user_id": str(uuid4())}, ["body", "user_id"]),
    ],
)
def test_grant_invalid_body_422(signed_in, body, loc):
    r = signed_in.post("/consents", json=body)
    assert r.status_code == 422
    assert loc in [e["loc"] for e in r.json()["detail"]]


def test_withdraw_invalid_purpose_422(signed_in):
    r = signed_in.post("/consents/everything/withdraw")
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["path", "purpose"]


def test_withdraw_terms_422_not_withdrawable(signed_in):
    # Bị chặn ở domain trước khi chạm store, nên không cần DB.
    r = signed_in.post("/consents/terms/withdraw")
    assert r.status_code == 422
    assert r.json() == {"detail": "consent_not_withdrawable"}


def test_grant_accepts_terms_purpose_in_body(signed_in):
    # Sai phiên bản bị chặn ở domain trước khi chạm store: chứng minh body nhận purpose terms.
    r = signed_in.post("/consents", json={"purpose": "terms", "document_version": "2026-09-v0"})
    assert r.status_code == 422
    assert r.json() == {"detail": "consent_document_outdated"}


def test_consent_routes_mounted():
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    assert {"get", "post"} <= set(paths["/consents"])
    assert {"post"} <= set(paths["/consents/{purpose}/withdraw"])
