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
from drugtime.modules.family.domain.consent_confirmation import Caregiver as CaregiverRecord
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


# --- adhoc-20261020-family-link-approval: người giám sát ------------------------------------

NEW_OPERATIONS = [
    ("GET", "/family/caregivers", None),
    ("PATCH", "/family/links/1/sharing", {"sharing_enabled": True}),
    ("POST", "/family/links/1/revoke", None),
]
NEW_USE_CASES = ("list_caregivers", "update_sharing", "revoke_link")


def caregiver_record(**kwargs):
    defaults = dict(
        link_id=1,
        family_user_id=uuid4(),
        family_full_name="Nguyen An",
        sharing_enabled=True,
        approved_at=NOW,
    )
    defaults.update(kwargs)
    return CaregiverRecord(**defaults)


@pytest.mark.parametrize("method,path,body", NEW_OPERATIONS)
def test_new_routes_missing_session_is_401(method, path, body):
    app = create_app()
    app.dependency_overrides[http.get_link_uow] = fake_uow
    assert TestClient(app).request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("method,path,body", NEW_OPERATIONS)
def test_new_routes_forbid_any_query(client, monkeypatch, method, path, body):
    for name in NEW_USE_CASES:
        monkeypatch.setattr(http, name, Mock(side_effect=AssertionError("use case called")))
    response = client.request(method, path + "?patient_id=other", json=body)
    assert response.status_code == 422 and isinstance(response.json()["detail"], list)


@pytest.mark.parametrize("path", ["/family/caregivers", "/family/links/1/revoke"])
@pytest.mark.parametrize("content", [b"{}", b"null", b" ", b'{"patient_id":"other"}'])
def test_caregivers_and_revoke_forbid_any_body(client, monkeypatch, path, content):
    for name in NEW_USE_CASES:
        monkeypatch.setattr(http, name, Mock(side_effect=AssertionError("use case called")))
    method = "GET" if path.endswith("caregivers") else "POST"
    assert client.request(method, path, content=content).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"sharing_enabled": "true"},
        {"sharing_enabled": 1},
        {"sharing_enabled": None},
        {"sharing_enabled": True, "patient_id": str(uuid4())},
    ],
)
def test_strict_sharing_body_rejected_before_use_case(client, monkeypatch, body):
    use_case = Mock()
    monkeypatch.setattr(http, "update_sharing", use_case)
    response = client.patch("/family/links/1/sharing", json=body)
    assert response.status_code == 422
    use_case.assert_not_called()


@pytest.mark.parametrize("action", ["sharing", "revoke"])
@pytest.mark.parametrize("link_id", ["0", "-1", "abc", "1.1", "9223372036854775808"])
def test_new_routes_invalid_path_id_is_422(client, action, link_id):
    path = f"/family/links/{link_id}/{action}"
    if action == "sharing":
        response = client.patch(path, json={"sharing_enabled": True})
    else:
        response = client.post(path)
    assert response.status_code == 422


def test_caregivers_success_only_contract_fields(client, monkeypatch):
    family = uuid4()
    records = [
        caregiver_record(family_user_id=family),
        caregiver_record(link_id=2, family_full_name=None, sharing_enabled=False, approved_at=None),
    ]
    monkeypatch.setattr(http, "list_caregivers", Mock(return_value=records))
    response = client.get("/family/caregivers")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0] == {
        "link_id": 1,
        "family_user_id": str(family),
        "family_full_name": "Nguyen An",
        "status": "active",
        "sharing_enabled": True,
        "approved_at": "2026-10-07T00:00:00Z",
    }
    assert items[1]["family_full_name"] is None and items[1]["approved_at"] is None


@pytest.mark.parametrize("enabled", [True, False])
def test_sharing_success_passes_value_and_returns_caregiver(client, monkeypatch, enabled):
    use_case = Mock(return_value=caregiver_record(sharing_enabled=enabled))
    monkeypatch.setattr(http, "update_sharing", use_case)
    response = client.patch("/family/links/7/sharing", json={"sharing_enabled": enabled})
    assert response.status_code == 200 and response.json()["sharing_enabled"] is enabled
    assert use_case.call_args.kwargs["enabled"] is enabled
    assert use_case.call_args.kwargs["link_id"] == 7


def test_revoke_success_shape(client, monkeypatch):
    c = context(LinkStatus.ACTIVE)
    monkeypatch.setattr(
        http,
        "revoke_link",
        Mock(return_value=replace(c.link, status=LinkStatus.REVOKED, revoked_at=NOW)),
    )
    response = client.post("/family/links/1/revoke")
    assert response.status_code == 200
    assert response.json() == {
        "link_id": 1,
        "family_user_id": str(c.link.family_user_id),
        "status": "revoked",
        "revoked_at": "2026-10-07T00:00:00Z",
    }


@pytest.mark.parametrize(
    "use_case,method,path,body,error,status",
    [
        (
            "update_sharing",
            "PATCH",
            "/family/links/1/sharing",
            {"sharing_enabled": True},
            Forbidden("consent_revoked"),
            403,
        ),
        (
            "update_sharing",
            "PATCH",
            "/family/links/1/sharing",
            {"sharing_enabled": True},
            NotFound("family_link_not_found"),
            404,
        ),
        (
            "update_sharing",
            "PATCH",
            "/family/links/1/sharing",
            {"sharing_enabled": False},
            Conflict("family_link_not_active"),
            409,
        ),
        (
            "update_sharing",
            "PATCH",
            "/family/links/1/sharing",
            {"sharing_enabled": True},
            Conflict("consent_confirmation_missing"),
            409,
        ),
        (
            "revoke_link",
            "POST",
            "/family/links/1/revoke",
            None,
            Conflict("invalid_link_transition"),
            409,
        ),
        ("revoke_link", "POST", "/family/links/1/revoke", None, Forbidden("khong_co_quyen"), 403),
        ("list_caregivers", "GET", "/family/caregivers", None, Forbidden("khong_co_quyen"), 403),
    ],
)
def test_new_routes_preserve_business_errors(
    client, monkeypatch, use_case, method, path, body, error, status
):
    monkeypatch.setattr(http, use_case, Mock(side_effect=error))
    response = client.request(method, path, json=body)
    assert response.status_code == status and response.json() == {"detail": str(error)}


@pytest.mark.parametrize("method,path,body", NEW_OPERATIONS)
@pytest.mark.parametrize("failure_at", ["connect", "operation", "commit"])
def test_new_routes_storage_errors_return_503(monkeypatch, method, path, body, failure_at):
    events = []

    @contextmanager
    def transaction():
        if failure_at == "connect":
            raise SQLAlchemyError("connection unavailable")
        try:
            yield object()
            if failure_at == "commit":
                raise SQLAlchemyError("commit unavailable")
            events.append("commit")
        except Exception:
            events.append("rollback")
            raise

    monkeypatch.setattr(http, "unit_of_work", transaction)
    c = context(LinkStatus.ACTIVE)
    values = {
        "list_caregivers": [],
        "update_sharing": caregiver_record(),
        "revoke_link": replace(c.link, status=LinkStatus.REVOKED, revoked_at=NOW),
    }

    for name, value in values.items():

        def operation(*args, value=value, **kwargs):
            if failure_at == "operation":
                raise SQLAlchemyError("audit unavailable")
            return value

        monkeypatch.setattr(http, name, operation)
    app = create_app()
    app.dependency_overrides[http.link_user] = lambda: identity.CurrentUser(uuid4(), False)
    response = TestClient(app, raise_server_exceptions=False).request(method, path, json=body)
    assert response.status_code == 503 and response.json() == {"detail": "service_unavailable"}
    assert "commit" not in events


@pytest.mark.parametrize("method,path,body", NEW_OPERATIONS)
def test_new_routes_admin_denied_before_lookup_and_audited(monkeypatch, method, path, body):
    app = create_app()
    admin = identity.CurrentUser(uuid4(), True)
    app.dependency_overrides[http.get_link_uow] = fake_uow
    app.dependency_overrides[http.link_user] = lambda: admin
    denied = Mock()
    monkeypatch.setattr(http.SqlLinkAudit, "denied", denied)
    for name in ("get_for_update", "list_caregivers"):
        monkeypatch.setattr(http.SqlLinks, name, Mock(side_effect=AssertionError("lookup")))
    response = TestClient(app).request(method, path, json=body)
    assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert denied.call_count == 1 and denied.call_args.args[:3] == (admin.id, None, None)
