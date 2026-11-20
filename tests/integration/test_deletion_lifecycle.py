from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.integration.test_deletion_creation_flow import BASE
from tests.integration.test_deletion_creation_flow import deletion_api as deletion_api

from drugtime.modules.consent.adapters.outbound.sql_consent import SqlDeletionRequests
from drugtime.modules.consent.application.execute_erasure import execute_erasure
from drugtime.shared.db import unit_of_work


def request_id(db, uid):
    return db.execute(
        text("SELECT id FROM data_deletion_requests WHERE user_id=:u"), {"u": uid}
    ).scalar_one()


@pytest.mark.parametrize("withdraw", ["consent", "link"])
def test_verify_create_lookup_cancel_replay_and_no_access_resurrection(
    client, auth, deletion_api, make, db, withdraw
):
    uid = make.user()
    family = make.family_of(uid)
    path = f"/patients/{uid}/schedules"
    assert client.get(path, headers=auth(family)).status_code == 200
    proof = deletion_api.issue(uid)
    assert client.post(BASE + "/otp/verify", headers=auth(uid), json=proof).status_code == 204
    assert client.get(BASE + "/current", headers=auth(uid)).json() is None
    created = deletion_api.confirm(uid, proof)
    assert created.status_code == 201
    assert client.get(path, headers=auth(family)).status_code == 403
    assert make.access_logs(uid)[-1]["result"] == "denied"
    for _ in range(2):
        lookup = client.get(BASE + "/current", headers=auth(uid))
        assert lookup.json() == created.json()
        assert lookup.headers["cache-control"] == "no-store"
    if withdraw == "consent":
        make.revoke_consent(uid, "family_sharing")
    else:
        db.execute(
            text(
                "UPDATE caregiver_links SET status='revoked', sharing_enabled=false, "
                "revoked_at=clock_timestamp() WHERE patient_user_id=:p AND family_user_id=:f"
            ),
            {"p": uid, "f": family},
        )
    for _ in range(2):
        response = client.post(BASE + "/current/cancel", headers=auth(uid))
        assert response.status_code == 204 and response.headers["cache-control"] == "no-store"
    assert client.get(BASE + "/current", headers=auth(uid)).json() is None
    assert client.get(path, headers=auth(family)).status_code == 403
    assert deletion_api.confirm(uid, proof).status_code == 422
    assert request_id(db, uid) is not None


def test_cancel_restores_only_existing_valid_access(client, auth, deletion_api, make):
    uid = make.user()
    family = make.family_of(uid)
    path = f"/patients/{uid}/schedules"
    deletion_api.confirm(uid, deletion_api.issue(uid))
    assert client.get(path, headers=auth(family)).status_code == 403
    assert client.post(BASE + "/current/cancel", headers=auth(uid)).status_code == 204
    assert client.get(path, headers=auth(family)).status_code == 200


@pytest.mark.parametrize(
    "offset,expected",
    [(timedelta(seconds=-1), 204), (timedelta(0), 409), (timedelta(seconds=1), 409)],
)
def test_cancel_deadline(client, auth, deletion_api, make, offset, expected):
    uid = make.user()
    result = deletion_api.confirm(uid, deletion_api.issue(uid)).json()
    deletion_api.clock.at = datetime.fromisoformat(result["scheduled_deletion_at"]) + offset
    assert client.post(BASE + "/current/cancel", headers=auth(uid)).status_code == expected


def test_worker_due_only_legacy_approval_and_cancelled_excluded(deletion_api, make, db):
    store = SqlDeletionRequests()
    uid = make.user()
    deletion_api.confirm(uid, deletion_api.issue(uid))
    rid = request_id(db, uid)
    with unit_of_work() as uow:
        assert rid not in store.approved_ids(uow)
        assert store.get(uow, rid) is None
    now = datetime.now(UTC)
    db.execute(
        text(
            "UPDATE data_deletion_requests SET requested_at=:t, "
            "scheduled_deletion_at=:t + interval '720 hours' WHERE id=:id"
        ),
        {"t": now - timedelta(days=31), "id": rid},
    )
    with unit_of_work() as uow:
        assert rid in store.approved_ids(uow)
        assert store.get(uow, rid).can_execute()
    with unit_of_work() as uow:
        store.mark_completed(uow, rid)
    with unit_of_work() as uow:
        assert rid not in store.approved_ids(uow)


def test_cancel_rejects_db_deadline_even_when_api_clock_lags(
    deletion_api, make, db, client, auth
):
    uid = make.user()
    deletion_api.confirm(uid, deletion_api.issue(uid))
    rid = request_id(db, uid)
    at = datetime.now(UTC) - timedelta(days=31)
    db.execute(
        text(
            "UPDATE data_deletion_requests SET requested_at=:t, "
            "scheduled_deletion_at=:t+interval '720 hours' WHERE id=:id"
        ),
        {"t": at, "id": rid},
    )
    deletion_api.clock.at = at + timedelta(days=30, seconds=-1)
    response = client.post(BASE + "/current/cancel", headers=auth(uid))
    assert response.status_code == 409
    assert response.json()["detail"] == "deletion_request_due"
    row = db.execute(
        text("SELECT cancelled_at,erasure_started_at FROM data_deletion_requests WHERE id=:id"),
        {"id": rid},
    ).one()
    assert row.cancelled_at is None and row.erasure_started_at is None


@pytest.mark.parametrize("first", ["cancel", "worker"])
def test_cancel_worker_serialization(first, client, auth, deletion_api, make, db):
    uid = make.user()
    deletion_api.confirm(uid, deletion_api.issue(uid))
    rid = request_id(db, uid)
    gate, release = Event(), Event()
    erased = []

    class PausedRequests(SqlDeletionRequests):
        def get(self, uow, request_id):
            from drugtime.modules.consent.adapters.outbound.sql_deletion_creation import (
                SqlDeletionCreation,
            )

            SqlDeletionCreation().lock(uow, uid)
            gate.set()
            assert release.wait(10)
            return super().get(uow, request_id)

    class Eraser:
        def erase_user(self, uow, user_id):
            erased.append(user_id)

    class Remover:
        def delete_account(self, user_id):
            pass

    if first == "cancel":
        # A queued job is stale by the time it acquires the user's lock.
        assert client.post(BASE + "/current/cancel", headers=auth(uid)).status_code == 204
        release.set()
    else:
        at = datetime.now(UTC) - timedelta(days=31)
        deletion_api.clock.at = datetime.now(UTC)
        db.execute(
            text(
                "UPDATE data_deletion_requests SET requested_at=:t, "
                "scheduled_deletion_at=:t+interval '720 hours' WHERE id=:id"
            ),
            {"t": at, "id": rid},
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        job = pool.submit(
            execute_erasure,
            rid,
            requests=PausedRequests(),
            erasers=[Eraser()],
            account_remover=Remover(),
            uow_factory=unit_of_work,
        )
        assert gate.wait(5)
        if first == "worker":
            cancel = pool.submit(client.post, BASE + "/current/cancel", headers=auth(uid))
            release.set()
            assert cancel.result(timeout=10).status_code == 409
        job.result(timeout=10)
    assert erased == ([uid] if first == "worker" else [])


def test_real_worker_erasers_use_worker_role_and_complete_only_after_auth(
    deletion_api, make, db, role_engines, client, auth, scheduled_body
):
    from contextlib import contextmanager

    from drugtime.runtime.job_runner import ERASURE_ORDER
    from drugtime.shared.db import SqlUnitOfWork

    uid = make.user()
    make.family_of(uid)
    db.execute(
        text(
            "INSERT INTO email_change_challenges(user_id,old_email,new_email) "
            "VALUES (:u,'old@example.test','new@example.test')"
        ),
        {"u": uid},
    )
    medication = make.catalog_medication()
    response = client.post("/medications", headers=auth(uid), json=scheduled_body(medication))
    assert response.status_code == 201, response.text
    deletion_api.confirm(uid, deletion_api.issue(uid))
    rid = request_id(db, uid)
    at = datetime.now(UTC) - timedelta(days=31)
    db.execute(
        text(
            "UPDATE data_deletion_requests SET requested_at=:t, "
            "scheduled_deletion_at=:t+interval '720 hours' WHERE id=:id"
        ),
        {"t": at, "id": rid},
    )

    @contextmanager
    def worker_uow():
        with role_engines["worker_role"].begin() as conn:
            yield SqlUnitOfWork(conn)

    class AuthUnavailable:
        def delete_account(self, user_id):
            raise RuntimeError("simulated auth outage")

    store = SqlDeletionRequests()
    with pytest.raises(RuntimeError):
        execute_erasure(
            rid,
            requests=store,
            erasers=ERASURE_ORDER,
            account_remover=AuthUnavailable(),
            uow_factory=worker_uow,
        )
    row = db.execute(
        text("SELECT status,erasure_attempts,last_error FROM data_deletion_requests WHERE id=:id"),
        {"id": rid},
    ).one()
    assert (
        row.status == "da_duyet" and row.erasure_attempts == 1 and row.last_error == "RuntimeError"
    )
    assert (
        db.execute(text("SELECT erased_at FROM users WHERE id=:u"), {"u": uid}).scalar_one()
        is not None
    )
    assert make.counts(uid) == {"meds": 0, "schedules": 0, "prescriptions": 0}
    for table in ("deletion_otp_challenges", "email_change_challenges"):
        assert (
            db.execute(
                text(f"SELECT count(*) FROM {table} WHERE user_id=:u"), {"u": uid}
            ).scalar_one()
            == 0
        )
    for table, column in (
        ("deletion_otp_challenges", "digest"),
        ("email_change_challenges", "old_email"),
    ):
        with role_engines["worker_role"].connect() as conn:
            with pytest.raises(DBAPIError) as denied:
                conn.execute(text(f"SELECT {column} FROM {table} WHERE user_id=:u"), {"u": uid})
            assert denied.value.orig.sqlstate == "42501"
    assert (
        db.execute(
            text("SELECT count(*) FROM caregiver_links WHERE patient_user_id=:u"), {"u": uid}
        ).scalar_one()
        == 0
    )
    removed = []

    class AuthSuccess:
        def delete_account(self, user_id):
            removed.append(user_id)

    execute_erasure(
        rid,
        requests=store,
        erasers=ERASURE_ORDER,
        account_remover=AuthSuccess(),
        uow_factory=worker_uow,
    )
    execute_erasure(
        rid,
        requests=store,
        erasers=ERASURE_ORDER,
        account_remover=AuthSuccess(),
        uow_factory=worker_uow,
    )
    assert removed == [uid]
    row = db.execute(
        text("SELECT status,completed_at,last_error FROM data_deletion_requests WHERE id=:id"),
        {"id": rid},
    ).one()
    assert row.status == "hoan_tat" and row.completed_at is not None and row.last_error is None


def test_worker_stops_after_five_failures_and_keeps_support_evidence(deletion_api, make, db):
    uid = make.user()
    deletion_api.confirm(uid, deletion_api.issue(uid))
    rid = request_id(db, uid)
    at = datetime.now(UTC) - timedelta(days=31)
    db.execute(
        text(
            "UPDATE data_deletion_requests SET requested_at=:t, "
            "scheduled_deletion_at=:t+interval '720 hours' WHERE id=:id"
        ),
        {"t": at, "id": rid},
    )
    store = SqlDeletionRequests()
    for _ in range(5):
        with unit_of_work() as uow:
            store.record_error(uow, rid, "ServiceUnavailable")
    with unit_of_work() as uow:
        assert rid not in store.approved_ids(uow)
        assert store.get(uow, rid) is None
    row = db.execute(
        text(
            "SELECT erasure_attempts,last_error,completed_at "
            "FROM data_deletion_requests WHERE id=:id"
        ),
        {"id": rid},
    ).one()
    assert row.erasure_attempts == 5 and row.last_error == "ServiceUnavailable"
    assert row.completed_at is None


def test_cancel_cannot_ack_after_erasure_a_even_if_api_clock_lags(
    deletion_api, make, db, client, auth
):
    uid = make.user()
    deletion_api.confirm(uid, deletion_api.issue(uid))
    rid = request_id(db, uid)
    at = datetime.now(UTC) - timedelta(days=31)
    db.execute(
        text(
            "UPDATE data_deletion_requests SET requested_at=:t, "
            "scheduled_deletion_at=:t+interval '720 hours' WHERE id=:id"
        ),
        {"t": at, "id": rid},
    )
    deletion_api.clock.at = at + timedelta(days=30, seconds=-1)
    entered, release = Event(), Event()

    class WaitingAuth:
        def delete_account(self, user_id):
            entered.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(
            execute_erasure,
            rid,
            requests=SqlDeletionRequests(),
            erasers=[],
            account_remover=WaitingAuth(),
            uow_factory=unit_of_work,
        )
        assert entered.wait(5)
        try:
            response = client.post(BASE + "/current/cancel", headers=auth(uid))
        finally:
            release.set()
        assert response.status_code == 409
        job.result(timeout=10)
