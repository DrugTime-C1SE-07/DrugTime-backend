"""Controlled occurrence port with real repositories/PEP/HTTP; no FCM claim."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import text
from test_adherence_history_api import HistoryData
from test_notification_access import AT, assert_item, insert_notification
from test_notification_access import inbox as inbox

from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    DeviceTokensAdapter,
    PatientNamesAdapter,
    SchedulesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlDoseLogs, SqlNotifications
from drugtime.modules.adherence.application.scan_missed_doses import scan
from drugtime.shared.db import SqlUnitOfWork, unit_of_work


def test_scan_snapshot_survives_catalog_schedule_edit_and_replay__AC2_AC3_AC4(
    db, make, client, auth, role_engines
):
    patient = make.user()
    family = make.family_of(patient)  # No Android token: iOS still gets inbox rows.
    data = HistoryData(db, make, client, auth, patient)
    occurrence = data.schedule(at=AT)
    schedules = Mock(wraps=SchedulesAdapter())
    schedules.occurrences_between.return_value = [occurrence]
    ports = dict(
        now=AT + timedelta(hours=3),
        grace=timedelta(hours=2),
        overlap=timedelta(minutes=10),
        cursor=Mock(),
        schedules=schedules,
        dose_logs=SqlDoseLogs(),
        access=AccessGuardAdapter(),
        tokens=DeviceTokensAdapter(),
        notifications=SqlNotifications(),
        patient_names=PatientNamesAdapter(),
    )
    ports["cursor"].get.return_value = None
    for _ in range(2):
        with role_engines["worker_role"].begin() as connection:
            assert scan(SqlUnitOfWork(connection), **ports) == []
    headers = auth(family)
    response = client.get("/notifications", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == body["unread_count"] == 1
    nid = body["items"][0]["id"]
    original = assert_item(client.get(f"/notifications/{nid}", headers=headers))
    assert original["medication_name"] == "Integration medicine"
    db.execute(
        text("UPDATE medications SET name='Tên thuốc đã sửa' WHERE id=:m"),
        {"m": occurrence.medication_id},
    )
    db.execute(
        text("UPDATE medication_schedules SET intake_time='19:00' WHERE id=:s"),
        {"s": occurrence.schedule_id},
    )
    current = assert_item(client.get(f"/notifications/{nid}", headers=headers))
    assert current == original
    assert len(data.snapshot()) == 1 and data.snapshot()[0].status == "bo_lo"
    before = data.snapshot()
    for _ in range(2):
        assert assert_item(
            client.patch(f"/notifications/{nid}", headers=headers, json={"is_read": True})
        )["is_read"]
    assert data.snapshot() == before
    assert client.get("/notifications", headers=headers).json()["unread_count"] == 0


def test_filter_offset_tied_order_and_global_badge__AC3_AC4(inbox):
    d = inbox
    read = insert_notification(d.db, d.family, d.patient, read=True)
    newest = insert_notification(d.db, d.family, d.patient)
    denied = d.make.user()
    insert_notification(d.db, d.family, denied)
    for params, ids, total in [
        ({"limit": 1}, [newest], 3),
        ({"limit": 1, "offset": 1}, [read], 3),
        ({"is_read": "true"}, [read], 1),
        ({"is_read": "false"}, [newest, d.nid], 2),
        ({"limit": 100, "offset": 100}, [], 3),
    ]:
        response = d.client.get("/notifications", headers=d.headers, params=params)
        assert response.status_code == 200
        body = response.json()
        assert [r["id"] for r in body["items"]] == ids
        assert body["total"] == total and body["unread_count"] == 2
    assert d.make.access_logs(denied)[-1]["result"] == "denied"


@pytest.mark.parametrize("confirmed", [False, True])
def test_worker_database_race_never_overwrites_confirmation__AC3(
    admin_engine, db, make, client, auth, wait_for_lock_waiters, confirmed
):
    patient = make.user()
    data = HistoryData(db, make, client, auth, patient)
    occurrence = data.schedule(at=AT)
    with admin_engine.execution_options(isolation_level="READ COMMITTED").connect() as blocker:
        tx = blocker.begin()
        if confirmed:
            blocker.execute(
                text(
                    "INSERT INTO dose_logs "
                    "(medication_schedule_id,scheduled_at,taken_at,status) "
                    "VALUES (:s,:at,:at,'da_uong')"
                ),
                {"s": occurrence.schedule_id, "at": AT},
            )
        else:
            SqlDoseLogs().mark_missed(SqlUnitOfWork(blocker), occurrence.schedule_id, AT)
        with ThreadPoolExecutor(max_workers=1) as pool:
            if confirmed:

                def work():
                    with unit_of_work() as uow:
                        return SqlDoseLogs().mark_missed(uow, occurrence.schedule_id, AT)
            else:

                def work():
                    return data.confirm(occurrence, AT + timedelta(minutes=30))

            future = pool.submit(work)
            try:
                wait_for_lock_waiters(1)
            finally:
                tx.commit()
            result = future.result(timeout=15)
    if confirmed:
        assert result is None
    rows = data.snapshot()
    assert len(rows) == 1 and rows[0].status == ("da_uong" if confirmed else "uong_tre")
