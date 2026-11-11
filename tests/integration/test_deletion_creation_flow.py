from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from drugtime.modules.access import api as access
from drugtime.modules.adherence import api as adherence
from drugtime.modules.adherence.adapters.outbound.other_modules import AccessGuardAdapter
from drugtime.modules.adherence.application import scan_missed_doses as scan_module
from drugtime.modules.adherence.domain.alert import Alert
from drugtime.modules.consent.adapters.inbound import deletion_http
from drugtime.modules.consent.adapters.outbound.sql_consent import SqlDeletionRequests
from drugtime.shared.db import get_engine, unit_of_work
from drugtime.shared.errors import Forbidden, ServiceUnavailable

BASE = "/data-deletion-requests"
AT = datetime(2026, 11, 11, 3, tzinfo=UTC)


@pytest.fixture
def deletion_api(client, monkeypatch, auth):
    clock = SimpleNamespace(at=AT)
    outbox = []
    emails = {}
    monkeypatch.setattr(deletion_http, "now", lambda: clock.at)
    monkeypatch.setattr(deletion_http.identity, "verified_email", emails.get)
    monkeypatch.setattr(deletion_http, "send_deletion_otp", lambda *args: outbox.append(args))
    monkeypatch.setattr(
        deletion_http, "get_settings", lambda: SimpleNamespace(deletion_otp_hmac_key="test-" * 8)
    )

    def issue(uid):
        emails[uid] = f"{uid}@example.test"
        r = client.post(BASE + "/otp", headers=auth(uid))
        assert r.status_code == 201, r.text
        assert r.headers["cache-control"] == "no-store"
        assert datetime.fromisoformat(r.json()["expires_at"]) == clock.at + timedelta(minutes=5)
        assert outbox[-1][0] == emails[uid]
        return {"challenge_id": r.json()["challenge_id"], "otp": outbox[-1][1]}

    def confirm(uid, payload):
        return client.post(BASE, headers=auth(uid), json=payload)

    return SimpleNamespace(issue=issue, confirm=confirm, clock=clock, emails=emails, outbox=outbox)


def rows(db, uid):
    return db.execute(
        text("SELECT * FROM data_deletion_requests WHERE user_id=:uid"), {"uid": uid}
    ).mappings().all()


def test_confirm_creates_one_request_with_server_deadline__AC1_AC3(deletion_api, make, db):
    uid = make.user()
    payload = deletion_api.issue(uid)
    assert not rows(db, uid)
    first = deletion_api.confirm(uid, payload)
    assert first.status_code == 201, first.text
    assert first.headers["cache-control"] == "no-store"
    result = first.json()
    assert set(result) == {"status", "requested_at", "scheduled_deletion_at"}
    assert result["status"] == "cho_xoa"
    assert datetime.fromisoformat(result["requested_at"]) == AT
    assert datetime.fromisoformat(result["scheduled_deletion_at"]) == AT + timedelta(days=30)
    repeated = deletion_api.confirm(uid, payload)
    assert repeated.status_code == 422 and repeated.json()["detail"] == "deletion_otp_invalid"
    deletion_api.clock.at += timedelta(minutes=1)
    retry = deletion_api.confirm(uid, deletion_api.issue(uid))
    assert retry.status_code == 200 and retry.json() == result
    (saved,) = rows(db, uid)
    assert saved["scheduled_deletion_at"] == AT + timedelta(days=30)


def test_invalid_identity_and_unverified_email_never_create_request__AC2(
    deletion_api, make, db, client, auth, admin_auth
):
    uid = make.user()
    outsider = make.user()
    admin, admin_headers = admin_auth
    r = client.post(BASE + "/otp")
    assert r.status_code == 401 and r.headers["cache-control"] == "no-store"
    assert client.post(BASE + "/otp", headers=admin_headers).status_code == 403
    r = client.post(BASE + "/otp", headers=auth(outsider))
    assert r.status_code == 409 and r.json()["detail"] == "verified_email_required"
    assert not deletion_api.outbox
    payload = deletion_api.issue(uid)
    r = deletion_api.confirm(outsider, payload)
    assert r.status_code == 422 and r.json()["detail"] == "deletion_otp_invalid"
    r = deletion_api.confirm(uid, {**payload, "user_id": str(outsider)})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
    assert all(not rows(db, user) for user in (uid, outsider, admin))


@pytest.mark.parametrize("variant", ["short", "long", "unicode", "wrong", "expired", "replaced"])
def test_invalid_otp_cannot_create_request__AC2(variant, deletion_api, make, db):
    uid = make.user()
    payload = deletion_api.issue(uid)
    if variant in {"short", "long", "unicode"}:
        payload["otp"] = {"short": "12345", "long": "1234567", "unicode": "１２３４５６"}[variant]
    if variant == "wrong":
        payload["otp"] = f"{(int(payload['otp']) + 1) % 1_000_000:06d}"
    if variant == "expired":
        deletion_api.clock.at += timedelta(minutes=5)
    if variant == "replaced":
        deletion_api.clock.at += timedelta(minutes=1)
        deletion_api.issue(uid)
    r = deletion_api.confirm(uid, payload)
    assert r.status_code == 422 and not rows(db, uid)
    detail = r.json()["detail"]
    if variant in {"short", "long", "unicode"}:
        assert isinstance(detail, list) and payload["otp"] not in r.text
    else:
        assert detail == "deletion_otp_invalid"


def test_rate_limit_persists_after_wrong_otp_and_resend__AC2(deletion_api, make, db, client, auth):
    uid = make.user()
    payload = deletion_api.issue(uid)
    assert client.post(BASE + "/otp", headers=auth(uid)).status_code == 429
    wrong = {**payload, "otp": f"{(int(payload['otp']) + 1) % 1_000_000:06d}"}
    for _ in range(4):
        assert deletion_api.confirm(uid, wrong).status_code == 422
    deletion_api.clock.at += timedelta(minutes=1)
    fresh = deletion_api.issue(uid)
    assert deletion_api.confirm(uid, wrong).status_code == 422
    r = deletion_api.confirm(uid, fresh)
    assert r.status_code == 429 and r.json()["detail"] == "deletion_otp_rate_limited"
    assert not rows(db, uid)


def test_delivery_failure_does_not_create_request__AC1_AC2(
    deletion_api, make, db, client, auth, monkeypatch
):
    uid = make.user()
    deletion_api.emails[uid] = "member@example.test"

    def unavailable(*_):
        raise ServiceUnavailable("service_unavailable")

    monkeypatch.setattr(deletion_http, "send_deletion_otp", unavailable)
    r = client.post(BASE + "/otp", headers=auth(uid))
    assert r.status_code == 503 and r.json()["detail"] == "service_unavailable"
    assert not rows(db, uid)


def test_insert_failure_leaves_otp_usable_and_never_acknowledges__AC1(deletion_api, make, db):
    uid = make.user()
    payload = deletion_api.issue(uid)

    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO data_deletion_requests"):
            raise RuntimeError("simulated insert failure")

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", fail_insert)
    try:
        response = deletion_api.confirm(uid, payload)
        assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
        assert not rows(db, uid)
    finally:
        event.remove(engine, "before_cursor_execute", fail_insert)
    assert deletion_api.confirm(uid, payload).status_code == 201
    assert len(rows(db, uid)) == 1


def test_concurrent_confirm_with_same_otp_only_commits_once__AC1_AC3(deletion_api, make, db):
    uid = make.user()
    payload = deletion_api.issue(uid)
    ready = Barrier(2)

    def submit():
        ready.wait(timeout=5)
        return deletion_api.confirm(uid, payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [pool.submit(submit) for _ in range(2)]
        outcomes = [first.result(timeout=15), second.result(timeout=15)]
    assert sorted(r.status_code for r in outcomes) == [201, 422]
    assert len(rows(db, uid)) == 1


@pytest.mark.parametrize("offset_seconds,expected", [(-1, 200), (0, 409), (1, 409)])
def test_deadline_handoff_keeps_request_out_of_legacy_worker__AC8(
    offset_seconds, expected, deletion_api, make, db
):
    uid = make.user()
    assert deletion_api.confirm(uid, deletion_api.issue(uid)).status_code == 201
    (row,) = rows(db, uid)
    deletion_api.clock.at = row["scheduled_deletion_at"] + timedelta(seconds=offset_seconds)
    retry = deletion_api.confirm(uid, deletion_api.issue(uid))
    assert retry.status_code == expected, retry.text
    if expected == 409:
        assert retry.json() == {"detail": "deletion_request_due"}
    assert rows(db, uid)[0]["scheduled_deletion_at"] == row["scheduled_deletion_at"]
    with unit_of_work() as uow:
        assert row["id"] not in SqlDeletionRequests().approved_ids(uow)


def test_deletion_revokes_family_reads_immediately_and_keeps_other_patient_visible__AC4_AC6(
    deletion_api, make, db, client, auth
):
    patient = make.user()
    family = make.family_of(patient)
    other = make.user(consents=("health_data", "family_sharing"))
    make.link(other, family)
    family_headers = auth(family)
    path = f"/patients/{patient}/schedules"
    notice = db.execute(
        text(
            "INSERT INTO notifications (user_id,about_patient_user_id,type,content,"
            "dedupe_key,medication_name,scheduled_at) "
            "VALUES (:f,:p,'canh_bao_bo_lo_lieu_nguoi_than','Test alert',:k,'Test med',:t) "
            "RETURNING id"
        ),
        {"f": family, "p": patient, "k": uuid4().hex, "t": AT},
    ).scalar_one()
    assert client.get(path, headers=family_headers).status_code == 200
    assert client.get(f"/notifications/{notice}", headers=family_headers).status_code == 200

    assert deletion_api.confirm(patient, deletion_api.issue(patient)).status_code == 201
    response = client.get(path, headers=family_headers)
    assert response.status_code == 403 and response.json() == {"detail": "khong_co_quyen"}
    assert make.access_logs(patient)[-1]["result"] == "denied"
    assert make.access_logs(patient)[-1]["actor_user_id"] == family
    assert client.get(path, headers=auth(patient)).status_code == 200
    family_list = client.get("/family/patients", headers=family_headers)
    assert family_list.status_code == 200
    assert [item["patient_id"] for item in family_list.json()["items"]] == [str(other)]
    assert client.get(f"/notifications/{notice}", headers=family_headers).status_code == 403
    assert client.get("/notifications", headers=family_headers).json()["items"] == []
    assert client.get(f"/patients/{other}/schedules", headers=family_headers).status_code == 200
    assert client.get(path, headers=auth(make.user())).status_code == 403
    assert make.access_logs(patient)[-1]["result"] == "denied"

    db.execute(
        text("UPDATE data_deletion_requests SET cancelled_at=:t WHERE user_id=:p"),
        {"t": AT + timedelta(minutes=1), "p": patient},
    )
    assert client.get(path, headers=family_headers).status_code == 200
    make.revoke_consent(patient, "family_sharing")
    assert client.get(path, headers=family_headers).status_code == 403
    assert make.access_logs(patient)[-1]["result"] == "denied"


def test_pending_deletion_blocks_meal_creation_and_family_alert_dispatch__AC4_AC5(
    deletion_api, make, monkeypatch
):
    patient = make.user(consents=("health_data", "ai_meal"))
    family = make.family_of(patient)
    assert deletion_api.confirm(patient, deletion_api.issue(patient)).status_code == 201
    with unit_of_work() as uow:
        with pytest.raises(Forbidden, match="khong_co_quyen"):
            access.authorize(
                uow,
                caller_id=patient,
                caller_is_admin=False,
                patient_id=patient,
                scope=access.Scope.MEAL,
                action=access.Action.WRITE,
            )
        assert access.authorized_caregivers(uow, patient) == []

    sent = []
    alert = Alert(1, family, "test-token", patient_id=patient)
    monkeypatch.setattr(
        scan_module, "scan", lambda *args, **kwargs: scan_module.ScanResult([alert])
    )
    monkeypatch.setattr(
        adherence,
        "get_settings",
        lambda: SimpleNamespace(missed_dose_grace_minutes=120, missed_dose_overlap_minutes=30),
    )
    notifier = SimpleNamespace(send=sent.extend)
    assert adherence.scan_missed_doses(unit_of_work, notifier=notifier) == 0
    assert sent == []


@pytest.mark.parametrize("first", ["dispatch", "deletion"])
def test_deletion_commit_races_fcm_send__AC4(
    first, deletion_api, make, db, wait_for_lock_waiters
):
    patient = make.user()
    family = make.family_of(patient)
    unrelated_patient = make.user()
    unrelated_family = make.family_of(unrelated_patient)
    alert = Alert(1, family, "family-device", patient_id=patient)
    other_alert = Alert(2, unrelated_family, "other-device", patient_id=unrelated_patient)
    proof = deletion_api.issue(patient)
    entered, release = Event(), Event()
    sent = []

    def send(alerts):
        if first == "dispatch" and alerts == [alert]:
            entered.set()
            assert release.wait(timeout=10)
        sent.extend(alerts)

    def pause_insert(_conn, _cursor, statement, _params, _context, _executemany):
        if statement.lstrip().upper().startswith("INSERT INTO DATA_DELETION_REQUESTS"):
            entered.set()
            assert release.wait(timeout=10)

    def dispatch(candidate):
        return scan_module.dispatch_authorized(
            unit_of_work, AccessGuardAdapter(), SimpleNamespace(send=send), [candidate]
        )[0]

    engine = get_engine()
    if first == "deletion":
        event.listen(engine, "after_cursor_execute", pause_insert)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            try:
                if first == "dispatch":
                    outgoing = pool.submit(dispatch, alert)
                    assert entered.wait(timeout=5)
                    deletion = pool.submit(deletion_api.confirm, patient, proof)
                    waiting = deletion
                else:
                    deletion = pool.submit(deletion_api.confirm, patient, proof)
                    assert entered.wait(timeout=5)
                    outgoing = pool.submit(dispatch, alert)
                    waiting = outgoing
                wait_for_lock_waiters(1, deadline_s=4)
                assert not waiting.done()
                assert pool.submit(dispatch, other_alert).result(timeout=2) == 1
                assert sent == [other_alert]
                assert rows(db, patient) == []
            finally:
                release.set()
            assert outgoing.result(timeout=5) == int(first == "dispatch")
            assert deletion.result(timeout=5).status_code == 201
    finally:
        if first == "deletion":
            event.remove(engine, "after_cursor_execute", pause_insert)
    assert len(rows(db, patient)) == 1
    assert dispatch(alert) == 0
    assert sent == ([other_alert, alert] if first == "dispatch" else [other_alert])


@pytest.mark.parametrize("operation", ["issue", "confirm"])
def test_deletion_lock_timeout_returns_503_and_allows_retry__AC1_AC3(
    operation, deletion_api, make, db, client, auth
):
    patient, other = make.user(), make.user()
    proof = deletion_api.issue(patient) if operation == "confirm" else None
    deletion_api.emails[patient] = f"{patient}@example.test"

    def request():
        if proof is not None:
            return deletion_api.confirm(patient, proof)
        return client.post(BASE + "/otp", headers=auth(patient))

    key = {"key": f"account-deletion:{patient}"}
    db.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), key)
    try:
        sent = len(deletion_api.outbox)
        response = request()
        assert response.status_code == 503
        assert response.json() == {"detail": "service_unavailable"}
        assert response.headers["cache-control"] == "no-store"
        assert len(deletion_api.outbox) == sent
        assert rows(db, patient) == []
        assert deletion_api.confirm(other, deletion_api.issue(other)).status_code == 201
    finally:
        db.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), key)
    assert request().status_code == 201
    assert len(rows(db, patient)) == int(operation == "confirm")


def test_fcm_lock_timeout_skips_only_the_locked_patient__AC4(make, db):
    patient, other_patient = make.user(), make.user()
    alert = Alert(1, make.family_of(patient), "family-device", patient_id=patient)
    other_alert = Alert(2, make.family_of(other_patient), "other-device", patient_id=other_patient)
    sent = []
    key = {"key": f"account-deletion:{patient}"}
    db.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), key)
    try:
        assert scan_module.dispatch_authorized(
            unit_of_work, AccessGuardAdapter(), SimpleNamespace(send=sent.extend),
            [alert, other_alert],
        ) == (1, [])
    finally:
        db.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), key)
    assert sent == [other_alert]


def test_migration_limits_roles_and_enforces_open_request_uniqueness__AC1_AC3(db, make):
    uid = make.user()
    assert db.execute(
        text("SELECT relrowsecurity FROM pg_class WHERE oid='deletion_otp_challenges'::regclass")
    ).scalar_one()
    for role in ("anon", "authenticated", "service_role", "worker_role"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not db.execute(
                text("SELECT has_table_privilege(:r, 'deletion_otp_challenges', :priv)"),
                {"r": role, "priv": privilege},
            ).scalar_one()
    insert = text(
        "INSERT INTO data_deletion_requests (user_id,requested_at,scheduled_deletion_at) "
        "VALUES (:u,:start,:end)"
    )
    with pytest.raises(IntegrityError):
        db.execute(insert, {"u": uid, "start": AT, "end": AT + timedelta(days=29)})
    values = {"u": uid, "start": AT, "end": AT + timedelta(days=30)}
    db.execute(insert, values)
    with pytest.raises(IntegrityError):
        db.execute(insert, values)
    db.execute(
        text("UPDATE data_deletion_requests SET cancelled_at=:t WHERE user_id=:u"),
        {"t": AT + timedelta(minutes=1), "u": uid},
    )
    db.execute(insert, values)
    assert len(rows(db, uid)) == 2
