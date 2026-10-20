from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from drugtime.main import create_app
from drugtime.modules.family.adapters.inbound import http
from drugtime.modules.family.adapters.outbound import sql_link_audit
from drugtime.modules.family.domain.consent_confirmation import PendingLink
from drugtime.modules.family.domain.link import LinkStatus
from drugtime.modules.identity import api as identity
from drugtime.shared.errors import Conflict, DomainError, Forbidden, NotFound
from tests.unit.test_family_manage_links import NOW, approve_context, context

OPERATIONS = [
    ("GET", "/family/links?status=pending"),
    ("POST", "/family/links/1/approve"),
    ("POST", "/family/links/1/reject"),
]
VALID = {
    "family_user_id": str(uuid4()),
    "consent_confirmed": True,
    "document_version": "2026-10-v1",
}


def fake_uow():
    yield object()


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides[http.get_link_uow] = fake_uow
    app.dependency_overrides[http.link_user] = lambda: identity.CurrentUser(uuid4(), False)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("method,path", OPERATIONS)
def test_missing_session_is_401(method, path):
    app = create_app()
    app.dependency_overrides[http.get_link_uow] = fake_uow
    response = TestClient(app).request(
        method, path, json=VALID if path.endswith("approve") else None
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "?status=active",
        "?status=pending&status=pending",
        "?status=pending&patient_id=other",
        "?status=pending&family_user_id=other",
        "?status=pending&page=1",
    ],
)
def test_list_rejects_missing_invalid_duplicate_or_extra_query(client, suffix, monkeypatch):
    use_case = Mock()
    monkeypatch.setattr(http, "list_pending_links", use_case)
    response = client.get("/family/links" + suffix)
    assert response.status_code == 422 and isinstance(response.json()["detail"], list)
    use_case.assert_not_called()


@pytest.mark.parametrize("path", ["/family/links?status=pending", "/family/links/1/reject"])
@pytest.mark.parametrize("content", [b"{}", b"null", b" ", b'{"patient_id":"other"}'])
def test_get_and_reject_forbid_any_body(client, path, content):
    response = client.request("GET" if "?" in path else "POST", path, content=content)
    assert response.status_code == 422


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize("link_id", ["0", "-1", "abc", "1.1", "9223372036854775808"])
def test_invalid_path_id_is_422(client, action, link_id):
    response = client.post(
        f"/family/links/{link_id}/{action}", json=VALID if action == "approve" else None
    )
    assert response.status_code == 422


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_decision_forbids_all_query_parameters(client, action):
    response = client.post(
        f"/family/links/1/{action}?patient_id=other", json=VALID if action == "approve" else None
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {**VALID, "consent_confirmed": False},
        {**VALID, "consent_confirmed": 1},
        {**VALID, "consent_confirmed": "true"},
        {**VALID, "document_version": ""},
        {**VALID, "document_version": "a" * 65},
        {**VALID, "document_version": 1},
        {**VALID, "family_user_id": "invalid"},
        {**VALID, "patient_id": str(uuid4())},
        {k: v for k, v in VALID.items() if k != "consent_confirmed"},
    ],
)
def test_strict_approval_body_rejected_before_use_case(client, body, monkeypatch):
    use_case = Mock()
    monkeypatch.setattr(http, "approve_link", use_case)
    response = client.post("/family/links/1/approve", json=body)
    assert response.status_code == 422
    use_case.assert_not_called()


def test_list_success_only_contract_fields(client, monkeypatch):
    family = uuid4()
    monkeypatch.setattr(
        http, "list_pending_links", Mock(return_value=[PendingLink(1, family, None, NOW)])
    )
    response = client.get("/family/links?status=pending")
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "link_id": 1,
                "family_user_id": str(family),
                "family_full_name": None,
                "status": "pending",
                "requested_at": "2026-10-07T00:00:00Z",
            }
        ]
    }


def test_approval_and_reject_success_shapes(client, monkeypatch):
    c = context()
    result = approve_context(c)
    use_case = Mock(return_value=result)
    monkeypatch.setattr(http, "approve_link", use_case)
    response = client.post("/family/links/1/approve", json=VALID)
    assert response.status_code == 200 and response.json()["sharing_enabled"] is False
    evidence = response.json()["consent_confirmation"]
    assert set(evidence) == {"id", "purpose", "document_version", "confirmed_at"}
    assert use_case.call_args.kwargs["consent_confirmed"] is True
    assert use_case.call_args.kwargs["family_user_id"] == UUID(VALID["family_user_id"])
    monkeypatch.setattr(
        http,
        "reject_link",
        Mock(return_value=replace(result.link, status=LinkStatus.REJECTED, rejected_at=NOW)),
    )
    response = client.post("/family/links/1/reject")
    assert response.status_code == 200
    assert set(response.json()) == {"link_id", "family_user_id", "status", "rejected_at"}


@pytest.mark.parametrize(
    "error,status",
    [
        (Forbidden("consent_revoked"), 403),
        (NotFound("family_link_not_found"), 404),
        (Conflict("link_approval_conflict"), 409),
        (DomainError("consent_document_outdated"), 422),
    ],
)
def test_business_errors_are_preserved(client, monkeypatch, error, status):
    monkeypatch.setattr(http, "approve_link", Mock(side_effect=error))
    response = client.post("/family/links/1/approve", json=VALID)
    assert response.status_code == status and response.json() == {"detail": str(error)}


@pytest.mark.parametrize("method,path", OPERATIONS)
@pytest.mark.parametrize("failure_at", ["connect", "operation", "commit", "denied_commit"])
def test_storage_and_commit_errors_return_503_before_sending_success(
    monkeypatch,
    method,
    path,
    failure_at,
):
    events = []

    @contextmanager
    def transaction():
        events.append("begin")
        if failure_at == "connect":
            raise SQLAlchemyError("connection unavailable")
        try:
            yield object()
            if failure_at == "commit":
                events.append("commit_failed")
                raise SQLAlchemyError("commit unavailable")
            events.append("commit")
        except Exception:
            events.append("rollback")
            raise

    monkeypatch.setattr(http, "unit_of_work", transaction)

    @contextmanager
    def denied_transaction():
        yield type("Uow", (), {"connection": Mock()})()
        events.append("denied_commit_failed")
        raise SQLAlchemyError("denied audit commit failed")

    monkeypatch.setattr(sql_link_audit, "unit_of_work", denied_transaction)
    c = context()
    approval = approve_context(c)
    value = (
        []
        if method == "GET"
        else approval
        if path.endswith("approve")
        else replace(c.link, status=LinkStatus.REJECTED, rejected_at=NOW)
    )

    def operation(*args, **kwargs):
        if failure_at == "operation":
            raise SQLAlchemyError("audit unavailable")
        if failure_at == "denied_commit":
            http.SqlLinkAudit().denied(uuid4(), None, None, "approve", "khong_co_quyen")
        return value

    for name in ("list_pending_links", "approve_link", "reject_link"):
        monkeypatch.setattr(http, name, operation)
    app = create_app()
    app.dependency_overrides[http.link_user] = lambda: identity.CurrentUser(uuid4(), False)
    response = TestClient(app, raise_server_exceptions=False).request(
        method, path, json=VALID if path.endswith("approve") else None
    )
    assert response.status_code == 503 and response.json() == {"detail": "service_unavailable"}
    assert "commit" not in events
    if failure_at != "connect":
        assert "rollback" in events


def test_authentication_database_error_is_guarded_by_same_uow(monkeypatch):
    @contextmanager
    def transaction():
        yield object()

    monkeypatch.setattr(http, "unit_of_work", transaction)
    monkeypatch.setattr(identity, "current_user", Mock(side_effect=SQLAlchemyError("auth DB")))
    app = create_app()
    response = TestClient(app, raise_server_exceptions=False).get("/family/links?status=pending")
    assert response.status_code == 503


@pytest.mark.parametrize("method,path", OPERATIONS)
def test_admin_http_denies_before_lookup_and_audits(monkeypatch, method, path):
    app = create_app()
    admin = identity.CurrentUser(uuid4(), True)
    app.dependency_overrides[http.get_link_uow] = fake_uow
    app.dependency_overrides[http.link_user] = lambda: admin
    denied = Mock()
    monkeypatch.setattr(http.SqlLinkAudit, "denied", denied)
    monkeypatch.setattr(http.SqlLinks, "get_for_update", Mock(side_effect=AssertionError("lookup")))
    monkeypatch.setattr(http.SqlLinks, "list_pending", Mock(side_effect=AssertionError("lookup")))
    response = TestClient(app).request(
        method, path, json=VALID if path.endswith("approve") else None
    )
    assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert denied.call_count == 1 and denied.call_args.args[:3] == (admin.id, None, None)
