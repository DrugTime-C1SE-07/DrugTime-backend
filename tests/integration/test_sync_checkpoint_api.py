"""Task 3.19: POST /doses/sync-checkpoints trên Postgres thật (api_role), PEP và contract."""

import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text

from drugtime.modules.adherence.adapters.inbound import http as dose_http
from drugtime.modules.adherence.api import eraser
from drugtime.shared.db import SqlUnitOfWork

PATH = "/doses/sync-checkpoints"
CONTRACT = json.loads(
    (Path(__file__).resolve().parents[3] / "api_contract/openapi.json").read_text("utf-8")
)
OPERATION = CONTRACT["paths"][PATH]["post"]


def checkpoint(db, user):
    return db.execute(
        text("SELECT synced_at FROM dose_sync_checkpoints WHERE user_id = :u"), {"u": user}
    ).scalar()


def db_now(db):
    return db.execute(text("SELECT clock_timestamp()")).scalar_one()


def test_patient_records_server_time_204__AC13(db, make, client, auth):
    patient = make.user()
    before = db_now(db)
    # Client không gửi giờ; body lạ (giờ thiết bị) không được dùng.
    response = client.post(PATH, headers=auth(patient), json={"synced_at": "2099-01-01T00:00:00Z"})
    after = db_now(db)
    assert response.status_code == 204 and response.content == b""
    synced = checkpoint(db, patient)
    assert before <= synced <= after


def test_never_moves_back__AC13(db, make, client, auth):
    patient = make.user()
    assert client.post(PATH, headers=auth(patient)).status_code == 204
    future = db_now(db) + timedelta(days=1)
    db.execute(
        text("UPDATE dose_sync_checkpoints SET synced_at = :t WHERE user_id = :u"),
        {"t": future, "u": patient},
    )
    assert client.post(PATH, headers=auth(patient)).status_code == 204
    assert checkpoint(db, patient) == future


def test_unauthenticated_401__AC13(client):
    response = client.post(PATH)
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing bearer token"}


def test_only_callers_own_checkpoint__AC13(db, make, client, auth):
    patient, other = make.user(), make.user()
    family = make.family_of(patient)
    assert client.post(PATH, headers=auth(family)).status_code == 204
    assert checkpoint(db, family) is not None
    assert checkpoint(db, patient) is None and checkpoint(db, other) is None


def test_two_devices_one_checkpoint__AC14(db, make, client, auth):
    patient = make.user()
    phone, tablet = auth(patient), auth(patient)  # hai phiên mobile của cùng P
    assert client.post(PATH, headers=phone).status_code == 204
    first = checkpoint(db, patient)
    assert client.post(PATH, headers=tablet).status_code == 204
    second = checkpoint(db, patient)
    assert second >= first
    rows = db.execute(
        text("SELECT count(*) FROM dose_sync_checkpoints WHERE user_id = :u"), {"u": patient}
    ).scalar_one()
    assert rows == 1


def test_admin_403_khong_co_quyen_logs_denied(db, client, admin_auth):
    admin_id, headers = admin_auth
    response = client.post(PATH, headers=headers)
    assert response.status_code == 403
    assert (
        response.json()
        == OPERATION["responses"]["403"]["content"]["application/json"]["examples"]["admin"][
            "value"
        ]
    )
    assert checkpoint(db, admin_id) is None
    logs = db.execute(
        text(
            "SELECT actor_role::text, result::text, rejection_reason FROM access_logs "
            "WHERE actor_user_id = :a ORDER BY id"
        ),
        {"a": admin_id},
    ).all()
    assert [tuple(r) for r in logs] == [("admin", "denied", "khong_co_quyen")]


def test_consent_revoked_403_no_record(db, make, client, auth):
    patient = make.user()
    make.revoke_consent(patient, "health_data")
    response = client.post(PATH, headers=auth(patient))
    assert response.status_code == 403
    assert (
        response.json()
        == OPERATION["responses"]["403"]["content"]["application/json"]["examples"][
            "consent_revoked"
        ]["value"]
    )
    assert checkpoint(db, patient) is None
    # Quy tắc chung của PEP: chính chủ với audit_self = False không ghi log, kể cả khi từ chối.
    assert make.access_logs(patient) == []


def test_success_writes_no_access_log(db, make, client, auth):
    patient = make.user()
    assert client.post(PATH, headers=auth(patient)).status_code == 204
    assert make.access_logs(patient) == []  # tự ghi checkpoint của mình: audit_self = False


def test_db_failure_503_records_nothing(db, make, client, auth, monkeypatch):
    patient = make.user()

    class Broken:
        def record(self, uow, user_id):
            raise RuntimeError("database down")

    monkeypatch.setattr(dose_http, "SqlSyncCheckpoints", Broken)
    response = client.post(PATH, headers=auth(patient))
    assert response.status_code == 503
    assert (
        response.json() == OPERATION["responses"]["503"]["content"]["application/json"]["example"]
    )
    assert checkpoint(db, patient) is None


def test_response_matches_contract__AC41(make, client, auth):
    assert set(OPERATION["responses"]) == {"204", "401", "403", "503"}
    assert OPERATION["operationId"] == "recordDoseSyncCheckpoint"
    assert "requestBody" not in OPERATION
    ok = client.post(PATH, headers=auth(make.user()))
    assert ok.status_code == 204 and ok.content == b""
    assert client.post(PATH).status_code == 401


def test_erase_removes_checkpoint_and_pending__AC16(db, make, client, auth, role_engines):
    from test_adherence_history_api import DAY, HistoryData

    patient = make.user()
    data = HistoryData(db, make, client, auth, patient)
    occ = data.schedule(DAY + timedelta(hours=8))
    assert client.post(PATH, headers=auth(patient)).status_code == 204
    db.execute(
        text(
            "INSERT INTO missed_dose_pending_verifications "
            "(medication_schedule_id, scheduled_at, patient_user_id) VALUES (:s, :at, :p)"
        ),
        {"s": occ.schedule_id, "at": occ.scheduled_at, "p": patient},
    )
    with role_engines["worker_role"].begin() as connection:
        eraser.erase_user(SqlUnitOfWork(connection), patient)
    assert checkpoint(db, patient) is None
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM missed_dose_pending_verifications WHERE patient_user_id = :p"
            ),
            {"p": patient},
        ).scalar_one()
        == 0
    )
