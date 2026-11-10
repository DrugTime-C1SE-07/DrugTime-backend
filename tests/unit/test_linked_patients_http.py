import secrets
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from drugtime.main import create_app
from drugtime.modules.access.adapters.inbound import linked_patients_http as http
from drugtime.modules.access.application.list_linked_patients import LinkedPatientView
from drugtime.modules.identity import api as identity
from drugtime.modules.identity.adapters.inbound import dependencies as auth
from drugtime.modules.identity.application.sign_in import issue_app_session
from drugtime.modules.identity.domain.user import SessionType
from drugtime.shared.config import get_settings
from drugtime.shared.db import get_uow
from drugtime.shared.errors import Forbidden

C, P = uuid4(), uuid4()


@pytest.fixture
def harness(monkeypatch):
    app = create_app()
    state = SimpleNamespace(
        app=app,
        events=[],
        fail=None,
        commit_fail=False,
        rows=[LinkedPatientView(P, "An")],
        calls=[],
    )
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(C, False)
    app.dependency_overrides[get_uow] = lambda: object()

    @contextmanager
    def transaction():
        state.events.append("begin")
        try:
            yield object()
            if state.commit_fail:
                raise SQLAlchemyError("commit unavailable")
            state.events.append("commit")
        except Exception:
            state.events.append("rollback")
            raise

    def use_case(uow, **kwargs):
        state.calls.append(kwargs)
        if state.fail is not None:
            raise state.fail
        return state.rows

    monkeypatch.setattr(http, "unit_of_work", transaction)
    monkeypatch.setattr(http, "list_linked_patients", use_case)
    with TestClient(app, raise_server_exceptions=False) as client:
        state.client = client
        yield state
    app.dependency_overrides.clear()


def test_success_commits_before_response(harness):
    response = harness.client.get("/family/patients")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"items": [{"patient_id": str(P), "patient_full_name": "An"}]}
    assert harness.events == ["begin", "commit"]
    assert harness.calls[0]["caller_id"] == C


def test_empty_and_null_name(harness):
    harness.rows = []
    assert harness.client.get("/family/patients").json() == {"items": []}
    harness.rows = [LinkedPatientView(P, None)]
    assert harness.client.get("/family/patients").json()["items"][0]["patient_full_name"] is None


@pytest.mark.parametrize(
    "query",
    [
        "patient_id=x",
        "user_id=x",
        "family_user_id=x",
        "limit=5",
        "cursor=x",
        "unknown=x",
        "patient_id=x&patient_id=y",
    ],
)
def test_query_input_rejected_no_store(harness, query):
    response = harness.client.get("/family/patients?" + query)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"][0]["loc"][0] == "query"
    assert harness.events == [] and harness.calls == []


@pytest.mark.parametrize("body", [b"{}", b"null", b"[]", b" ", b"{bad", b'"x"'])
def test_all_bodies_rejected(harness, body):
    response = harness.client.request("GET", "/family/patients", content=body)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"][0]["loc"] == ["body"]
    assert harness.events == []


def test_admin_error_and_rollback(harness):
    harness.app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(C, True)
    harness.fail = Forbidden("khong_co_quyen")
    response = harness.client.get("/family/patients")
    assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert response.headers["cache-control"] == "no-store"
    assert harness.events == ["begin", "rollback"]
    assert harness.calls[0]["caller_is_admin"] is True


def test_commit_failure_returns_503_before_response(harness):
    harness.commit_fail = True
    response = harness.client.get("/family/patients")
    assert response.status_code == 503
    assert response.json() == {"detail": "service_unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert harness.events == ["begin", "rollback"]


def test_dependency_sql_failure_returns_503_no_store(harness):
    def unavailable():
        raise SQLAlchemyError("database unavailable")

    harness.app.dependency_overrides[identity.current_user] = unavailable
    response = harness.client.get("/family/patients")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "service_unavailable"}
    assert harness.events == []


def test_audit_sql_failure_rolls_back(harness):
    harness.fail = SQLAlchemyError("allowed insert unavailable")
    response = harness.client.get("/family/patients")
    assert response.status_code == 503
    assert response.json() == {"detail": "service_unavailable"}
    assert harness.events == ["begin", "rollback"]


def test_http_auth_validation_errors_no_store(harness, monkeypatch):
    harness.app.dependency_overrides.pop(identity.current_user)
    monkeypatch.setenv("SESSION_JWT_SECRET", secrets.token_hex(32))
    get_settings.cache_clear()
    user = SimpleNamespace(id=C, is_admin=False, erased=False)
    monkeypatch.setattr(auth, "SqlUsers", lambda uow: SimpleNamespace(get=lambda uid: user))
    try:
        token = issue_app_session(C, SessionType.MOBILE, datetime.now(UTC)).token
        foreign = jwt.encode({"sub": str(C), "aud": "authenticated"}, secrets.token_hex(32))
        for header in (None, "Bearer invalid", "Bearer " + foreign):
            response = harness.client.get(
                "/family/patients?patient_id=x",
                headers={} if header is None else {"Authorization": header},
            )
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
        response = harness.client.get(
            "/family/patients", headers={"Authorization": "Bearer " + token}
        )
        assert response.status_code == 200
    finally:
        get_settings.cache_clear()


def test_admin_access_log_route_still_registered(harness):
    assert "/admin/access-logs" in harness.app.openapi()["paths"]
