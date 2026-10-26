"""Task 3.21: real api_role transactions, current PEP decisions and audit failure."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    PatientNamesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlNotifications
from drugtime.modules.adherence.application.manage_notifications import get_notification
from drugtime.shared.db import get_engine, unit_of_work
from drugtime.shared.errors import Forbidden

AT = datetime(2026, 10, 20, 1, tzinfo=UTC)
CONTRACT = json.loads(
    (Path(__file__).resolve().parents[3] / "api_contract/openapi.json").read_text("utf-8")
)


def assert_item(response):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    schema = CONTRACT["components"]["schemas"]["NotificationItem"]
    assert set(body) == set(schema["required"])
    assert body["type"] == "canh_bao_bo_lo_lieu_nguoi_than"
    assert isinstance(body["id"], int) and body["id"] > 0
    assert isinstance(body["is_read"], bool)
    assert datetime.fromisoformat(body["created_at"].replace("Z", "+00:00")).utcoffset() is not None
    if body["scheduled_at"] is not None:
        assert (
            datetime.fromisoformat(body["scheduled_at"].replace("Z", "+00:00")).utcoffset()
            is not None
        )
    return body


def insert_notification(db, family, patient, *, read=False, name="Thuốc snapshot", at=AT):
    return db.execute(
        text(
            "INSERT INTO notifications (user_id,about_patient_user_id,type,content,"
            "dedupe_key,medication_name,scheduled_at,is_read,created_at) "
            "VALUES (:f,:p,'canh_bao_bo_lo_lieu_nguoi_than','Nội dung kiểm thử',"
            ":k,:name,:at,:read,:at) RETURNING id"
        ),
        {"f": family, "p": patient, "k": uuid4().hex, "name": name, "at": at, "read": read},
    ).scalar_one()


@pytest.fixture
def inbox(db, make, auth, client):
    patient = make.user()
    family = make.family_of(patient)
    nid = insert_notification(db, family, patient)
    return SimpleNamespace(
        db=db,
        make=make,
        patient=patient,
        family=family,
        nid=nid,
        headers=auth(family),
        client=client,
    )


def call(data, operation, *, headers=None):
    headers = data.headers if headers is None else headers
    if operation == "list":
        return data.client.get("/notifications", headers=headers)
    if operation == "detail":
        return data.client.get(f"/notifications/{data.nid}", headers=headers)
    return data.client.patch(f"/notifications/{data.nid}", headers=headers, json={"is_read": True})


def test_allowed_list_detail_patch_use_read_audit_and_replay__AC3_AC4(inbox):
    d = inbox
    before_doses = d.db.execute(text("SELECT count(*) FROM dose_logs")).scalar_one()
    body = call(d, "list").json()
    assert (body["total"], body["unread_count"]) == (1, 1)
    item = assert_item(call(d, "detail"))
    assert item["medication_name"] == "Thuốc snapshot"
    assert item["about_patient_user_id"] == str(d.patient)
    assert item["about_patient_name"] == "Test User" and not item["is_read"]
    for _ in range(2):
        assert assert_item(call(d, "patch"))["is_read"] is True
    assert call(d, "list").json()["unread_count"] == 0
    assert d.db.execute(text("SELECT count(*) FROM dose_logs")).scalar_one() == before_doses
    logs = d.make.access_logs(d.patient)
    assert len(logs) == 5
    assert all(
        r["result"] == "allowed"
        and r["actor_user_id"] == d.family
        and r["data_scope"] == "lich_su_tuan_thu"
        for r in logs
    )


@pytest.mark.parametrize(
    "change", ["unlinked", "inactive", "sharing_off", "health_data", "family_sharing"]
)
@pytest.mark.parametrize("operation", ["list", "detail", "patch"])
def test_revocation_next_request_filters_counts_or_denies_and_audits__AC5(inbox, change, operation):
    d = inbox
    assert call(d, "detail").status_code == 200
    # Autocommit setup connection differs from the API connection; reuse the same bearer.
    if change in ("health_data", "family_sharing"):
        d.make.revoke_consent(d.patient, change)
    elif change == "sharing_off":
        d.db.execute(
            text("UPDATE caregiver_links SET sharing_enabled=false WHERE patient_user_id=:p"),
            {"p": d.patient},
        )
    else:
        d.db.execute(
            text(
                "UPDATE caregiver_links SET status='revoked',revoked_at=now() "
                "WHERE patient_user_id=:p"
            ),
            {"p": d.patient},
        )
    response = call(d, operation)
    assert response.headers["cache-control"] == "no-store"
    if operation == "list":
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "unread_count": 0}
    else:
        assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert d.make.access_logs(d.patient)[-1]["result"] == "denied"
    assert not d.db.execute(
        text("SELECT is_read FROM notifications WHERE id=:i"), {"i": d.nid}
    ).scalar_one()


@pytest.mark.parametrize("operation", ["detail", "patch"])
def test_other_recipient_and_unknown_id_return_404__AC5(inbox, auth, operation):
    d = inbox
    stranger = d.make.user()
    response = call(d, operation, headers=auth(stranger))
    assert response.status_code == 404 and response.json() == {"detail": "notification_not_found"}
    assert d.make.access_logs(d.patient) == []
    response = d.client.get("/notifications/9223372036854775807", headers=d.headers)
    assert response.status_code == 404


def test_mixed_patient_filter_and_selector_tamper_do_not_leak__AC3_AC5(inbox):
    d = inbox
    other = d.make.user()
    hidden = insert_notification(d.db, d.family, other)
    response = d.client.get(
        "/notifications",
        headers=d.headers,
        params={"patient_id": str(d.patient), "user_id": str(other)},
    )
    assert response.status_code == 200
    assert [r["id"] for r in response.json()["items"]] == [d.nid]
    assert response.json()["total"] == response.json()["unread_count"] == 1
    assert d.make.access_logs(other)[-1]["result"] == "denied"
    response = d.client.patch(
        f"/notifications/{hidden}",
        headers=d.headers,
        json={"is_read": True, "patient_id": str(d.patient)},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("operation", ["list", "detail", "patch"])
def test_admin_session_forbidden__AC5(inbox, admin_auth, operation):
    _, headers = admin_auth
    assert call(inbox, operation, headers=headers).status_code == 403


@pytest.mark.parametrize("operation", ["list", "detail", "patch"])
@pytest.mark.parametrize("failure", ["facts", "allowed_insert", "denied_insert", "commit"])
def test_access_audit_commit_failure_returns_503_without_health_or_write__AC5(
    inbox, operation, failure
):
    d = inbox
    if failure == "denied_insert":
        d.make.revoke_consent(d.patient, "family_sharing")

    def inject(conn, cursor, statement, parameters, context, executemany):
        if (failure == "facts" and "FROM user_consents" in statement) or (
            failure.endswith("insert") and "INSERT INTO access_logs" in statement
        ):
            raise RuntimeError("injected database failure")

    def fail_commit(conn):
        raise RuntimeError("injected commit failure")

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", inject)
    if failure == "commit":
        event.listen(engine, "commit", fail_commit)
    try:
        response = call(d, operation)
    finally:
        event.remove(engine, "before_cursor_execute", inject)
        if failure == "commit":
            event.remove(engine, "commit", fail_commit)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": "notification_access_unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert d.make.access_logs(d.patient) == []
    assert not d.db.execute(
        text("SELECT is_read FROM notifications WHERE id=:i"), {"i": d.nid}
    ).scalar_one()


def test_denied_audit_survives_request_transaction_rollback__AC5(inbox):
    d = inbox
    d.make.revoke_consent(d.patient, "family_sharing")
    with pytest.raises(Forbidden):
        with unit_of_work() as uow:
            get_notification(
                uow,
                user_id=d.family,
                notification_id=d.nid,
                notifications=SqlNotifications(),
                access=AccessGuardAdapter(),
                patient_names=PatientNamesAdapter(),
            )
    assert [r["result"] for r in d.make.access_logs(d.patient)] == ["denied"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_invalid_pagination_is_422_no_store__AC3(inbox, params):
    response = inbox.client.get("/notifications", headers=inbox.headers, params=params)
    assert response.status_code == 422 and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("limit", [1, 100])
def test_valid_pagination_boundaries__AC3(inbox, limit):
    response = inbox.client.get(
        "/notifications", headers=inbox.headers, params={"limit": limit, "offset": 0}
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [inbox.nid]


@pytest.mark.parametrize("link", ["missing", "pending"])
@pytest.mark.parametrize("operation", ["list", "detail", "patch"])
def test_initial_missing_or_pending_link_denied_with_audit__AC5(inbox, link, operation):
    d = inbox
    patient = d.make.user(consents=("health_data", "family_sharing"))
    if link == "pending":
        d.make.link(patient, d.family, status="pending")
    d.db.execute(
        text("UPDATE notifications SET about_patient_user_id=:p WHERE id=:i"),
        {"p": patient, "i": d.nid},
    )
    response = call(d, operation)
    if operation == "list":
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "unread_count": 0}
    else:
        assert response.status_code == 403
    assert [row["result"] for row in d.make.access_logs(patient)] == ["denied"]


@pytest.mark.parametrize("operation", ["list", "detail", "patch"])
def test_missing_session_returns_401_no_store__AC5(inbox, operation):
    response = call(inbox, operation, headers={})
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
