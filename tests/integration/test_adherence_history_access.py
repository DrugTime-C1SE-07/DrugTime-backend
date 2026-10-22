"""PEP thật, api_role, audit append-only và thu hồi quyền ở request kế tiếp."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from test_adherence_history_api import assert_contract
from test_adherence_history_api import history_data as _history_data

from drugtime.main import create_app
from drugtime.modules.adherence.adapters.inbound import history_http
from drugtime.modules.identity.application.sign_in import issue_app_session
from drugtime.modules.identity.domain.user import SessionType
from drugtime.shared.db import get_engine

SCOPE = "lich_su_tuan_thu"
history_data = _history_data


def read_as(data, caller, *, patient=None, headers=None, **params):
    return data.client.get(
        "/adherence",
        params={"patient_id": patient or data.patient, **params},
        headers=headers if headers is not None else data.auth(caller),
    )


def audit(actor, role, result, reason=None):
    return dict(
        actor_user_id=actor,
        actor_role=role,
        data_scope=SCOPE,
        result=result,
        rejection_reason=reason,
    )


def test_self_and_family_success_are_audited_with_minimal_metadata__AC1_AC2(history_data):
    data = history_data
    occurrence = data.schedule()
    data.log(occurrence, "da_uong")
    family = data.make.family_of(data.patient)
    patient_body = assert_contract(data.day())
    family_body = assert_contract(
        read_as(data, family, **{"from": "2026-10-19", "to": "2026-10-19"})
    )
    assert patient_body == family_body
    assert data.make.access_logs(data.patient) == [
        audit(data.patient, "patient", "allowed"),
        audit(family, "family", "allowed"),
    ]
    columns = data.db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='access_logs'"
        )
    )
    assert not {"medication_name", "taken_at", "scheduled_at", "payload"} & {r[0] for r in columns}


@pytest.mark.parametrize(
    "case", ["unlinked", "health_consent", "family_consent", "sharing_off", "admin"]
)
def test_unlinked_missing_consents_sharing_off_admin_denied_and_audited__AC11(history_data, case):
    data = history_data
    data.log(data.schedule(), "da_uong")
    if case in ("unlinked", "admin"):
        caller = data.make.user(admin=case == "admin")
        expected_role = "admin" if case == "admin" else "khong_co_quyen"
    else:
        caller = data.make.family_of(data.patient)
        expected_role = "khong_co_quyen"
        if case == "health_consent":
            data.make.revoke_consent(data.patient, "health_data")
        elif case == "family_consent":
            data.make.revoke_consent(data.patient, "family_sharing")
        else:
            data.db.execute(
                text("UPDATE caregiver_links SET sharing_enabled=false WHERE patient_user_id=:p"),
                {"p": data.patient},
            )
    before = data.snapshot()
    response = read_as(data, caller)
    assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert response.headers["cache-control"] == "no-store"
    assert data.make.access_logs(data.patient) == [
        audit(caller, expected_role, "denied", "khong_co_quyen")
    ]
    assert data.snapshot() == before


@pytest.mark.parametrize("access", ["self", "linked"])
def test_admin_self_and_linked_history_denied_and_audited__AC3_AC6_AC7(history_data, access):
    data = history_data
    admin = data.make.user(admin=True)
    if access == "self":
        data.patient = admin
    else:
        data.make.consent(data.patient, "family_sharing")
        data.make.link(data.patient, admin)
    data.log(data.schedule(), "da_uong")
    before = data.snapshot()

    response = read_as(data, admin)

    assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert response.headers["cache-control"] == "no-store"
    assert data.make.access_logs(data.patient) == [
        audit(admin, "admin", "denied", "khong_co_quyen")
    ]
    assert data.snapshot() == before


def test_family_patient_selector_tamper_does_not_read_other_patient__AC11(history_data):
    data = history_data
    family = data.make.family_of(data.patient)
    other = data.make.user()
    assert_contract(read_as(data, family))
    response = read_as(data, family, patient=other)
    assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert data.make.access_logs(other) == [
        audit(family, "khong_co_quyen", "denied", "khong_co_quyen")
    ]
    assert len(data.make.access_logs(data.patient)) == 1


@pytest.mark.parametrize("change", ["health_consent", "family_consent", "sharing_off", "unlink"])
def test_revoke_sharing_off_unlink_denies_immediate_next_request_same_token__AC12(
    history_data, change
):
    data = history_data
    family = data.make.family_of(data.patient)
    headers = data.auth(family)
    assert_contract(read_as(data, family, headers=headers))
    if change.endswith("consent"):
        data.make.revoke_consent(
            data.patient, "health_data" if change == "health_consent" else "family_sharing"
        )
    elif change == "sharing_off":
        data.db.execute(
            text("UPDATE caregiver_links SET sharing_enabled=false WHERE patient_user_id=:p"),
            {"p": data.patient},
        )
    else:
        data.db.execute(
            text(
                "UPDATE caregiver_links SET status='revoked',revoked_at=now() "
                "WHERE patient_user_id=:p"
            ),
            {"p": data.patient},
        )
    response = read_as(data, family, headers=headers)
    assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert data.make.access_logs(data.patient) == [
        audit(family, "family", "allowed"),
        audit(family, "khong_co_quyen", "denied", "khong_co_quyen"),
    ]


def test_self_without_health_consent_denied_with_self_audit__AC11(history_data):
    data = history_data
    data.make.revoke_consent(data.patient, "health_data")
    response = data.read()
    assert response.status_code == 403 and response.json() == {"detail": "consent_revoked"}
    assert data.make.access_logs(data.patient) == [
        audit(data.patient, "patient", "denied", "consent_revoked")
    ]


def test_unknown_patient_returns_same_generic_403_without_fk_audit__AC11(history_data):
    data = history_data
    unknown = uuid4()
    existing = data.make.user()
    first = read_as(data, data.patient, patient=unknown)
    second = read_as(data, data.patient, patient=existing)
    assert first.status_code == second.status_code == 403
    assert first.json() == second.json() == {"detail": "khong_co_quyen"}
    assert data.make.access_logs(unknown) == []
    assert len(data.make.access_logs(existing)) == 1


@pytest.mark.parametrize(
    "failure", ["allowed_insert", "commit", "denied_insert", "permission_read"]
)
def test_audit_permission_and_commit_failure_fail_closed_without_health__AC13(
    history_data, monkeypatch, failure
):
    data = history_data
    data.log(data.schedule(), "da_uong")
    if failure == "denied_insert":
        data.make.revoke_consent(data.patient, "health_data")
    before = data.snapshot()
    real = history_http.unit_of_work
    history_selects = []

    @contextmanager
    def failed_commit():
        with real() as uow:
            yield uow
            raise RuntimeError("injected commit failure")

    def fail_or_record(conn, cursor, statement, parameters, context, executemany):
        if "WITH patient_schedules AS" in statement:
            history_selects.append(statement)
        if failure.endswith("insert") and "INSERT INTO access_logs" in statement:
            raise RuntimeError("injected audit failure")
        if failure == "permission_read" and "FROM user_consents" in statement:
            raise RuntimeError("injected permission failure")

    if failure == "commit":
        monkeypatch.setattr(history_http, "unit_of_work", failed_commit)
    engine = get_engine()
    event.listen(engine, "before_cursor_execute", fail_or_record)
    try:
        response = TestClient(create_app(), raise_server_exceptions=False).get(
            "/adherence", headers=data.auth(data.patient)
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail_or_record)
    assert response.status_code == 500 and response.json() == {"detail": "Internal server error"}
    assert response.headers["cache-control"] == "no-store"
    assert data.make.access_logs(data.patient) == [] and data.snapshot() == before
    if failure != "commit":
        assert history_selects == []


def test_denied_audit_survives_outer_transaction_rollback__AC13(history_data, monkeypatch):
    data = history_data
    data.make.revoke_consent(data.patient, "health_data")
    real = history_http.unit_of_work
    observed = []

    @contextmanager
    def track_rollback():
        try:
            with real() as uow:
                yield uow
        except Exception:
            observed.append("rolled_back")
            raise

    monkeypatch.setattr(history_http, "unit_of_work", track_rollback)
    response = data.read()
    assert response.status_code == 403 and observed == ["rolled_back"]
    assert data.make.access_logs(data.patient) == [
        audit(data.patient, "patient", "denied", "consent_revoked")
    ]


@pytest.mark.parametrize("kind", ["missing", "invalid", "expired", "erased"])
def test_authentication_401_and_no_store_without_health_payload__AC14(history_data, kind):
    data = history_data
    data.log(data.schedule(), "da_uong")
    if kind == "missing":
        headers = {}
    elif kind == "invalid":
        headers = {"Authorization": "Bearer invalid-token"}
    elif kind == "expired":
        token = issue_app_session(
            data.patient, SessionType.MOBILE, datetime.now(UTC) - timedelta(days=100)
        ).token
        headers = {"Authorization": f"Bearer {token}"}
    else:
        headers = data.auth(data.patient)
        data.db.execute(
            text(
                "UPDATE users SET erased_at=now(),full_name=NULL,date_of_birth=NULL,gender=NULL,"
                "email=NULL,phone_number=NULL WHERE id=:p"
            ),
            {"p": data.patient},
        )
    response = data.client.get("/adherence", headers=headers)
    assert response.status_code == 401 and set(response.json()) == {"detail"}
    assert response.headers["cache-control"] == "no-store"
    assert data.make.access_logs(data.patient) == []
