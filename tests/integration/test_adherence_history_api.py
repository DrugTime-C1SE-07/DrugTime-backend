"""Lịch sử tuân thủ trên PostgreSQL thật, clock cố định; không gửi FCM."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import ProgrammingError

from drugtime.modules.adherence.adapters.inbound import history_http
from drugtime.modules.adherence.adapters.inbound import http as dose_http
from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    SchedulesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import (
    SqlDoseLogs,
    SqlNotifications,
    SqlPendingVerifications,
    SqlSyncCheckpoints,
)
from drugtime.modules.adherence.application.confirm_doses import confirm_doses
from drugtime.modules.adherence.application.scan_missed_doses import scan
from drugtime.modules.adherence.domain.dose import LATE_CONFIRMATION_WINDOW, DoseConfirmation
from drugtime.shared.db import SqlUnitOfWork, get_engine

VN = ZoneInfo("Asia/Ho_Chi_Minh")
DAY = datetime(2026, 10, 19, tzinfo=VN)
# 3.19: liều qua hạn chót chỉ suy ra bo_lo khi patient đã đồng bộ sau hạn chót. Các test 3.23
# mặc định patient đã đồng bộ (checkpoint xa trong tương lai); test 3.19 tự xóa/đặt checkpoint.
FULLY_SYNCED = DAY + timedelta(days=365)
STATUSES = ("da_uong", "uong_tre", "bo_lo", "cho_xac_nhan", "chua_xac_minh")
CONTRACT = json.loads(
    (Path(__file__).resolve().parents[3] / "api_contract/openapi.json").read_text(encoding="utf-8")
)


def assert_contract(response):
    """Assert wire fields against the approved contract, not production response models."""
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    schemas = CONTRACT["components"]["schemas"]
    kind = "Date" if body["group_by"] == "date" else "Medication"
    assert set(body) == set(schemas[f"AdherenceBy{kind}Response"]["required"])
    assert body["timezone"] == "Asia/Ho_Chi_Minh"
    assert body["as_of"].endswith("+07:00")
    summary = body["summary"]
    assert set(summary) == set(schemas["AdherenceSummary"]["required"])
    assert summary["total"] == sum(
        summary[s] for s in ("taken", "late", "missed", "pending", "unverified")
    )
    assert summary["counted"] == summary["total"] - summary["pending"] - summary["unverified"]
    synced = body["patient_last_synced_at"]
    assert synced is None or synced.endswith("+07:00")
    assert (summary["adherence_rate"] is None) == (summary["counted"] == 0)
    assert summary["total"] == sum(group["summary"]["total"] for group in body["groups"])
    keys = []
    for group in body["groups"]:
        assert set(group) == set(schemas[f"Adherence{kind}Group"]["required"])
        assert group["doses"] and len(group["doses"]) == group["summary"]["total"]
        for dose in group["doses"]:
            assert set(dose) == set(schemas["AdherenceDose"]["required"])
            assert dose["scheduled_at"].endswith("+07:00")
            assert dose["status"] in STATUSES
            assert dose["status_source"] in ("recorded", "inferred")
            if dose["status"] in ("da_uong", "uong_tre"):
                assert dose["taken_at"].endswith("+07:00")
                assert dose["status_source"] == "recorded"
            else:
                assert dose["taken_at"] is None
            if dose["status"] in ("cho_xac_nhan", "chua_xac_minh"):
                assert dose["status_source"] == "inferred"
            keys.append((dose["schedule_id"], dose["scheduled_at"]))
    assert len(keys) == len(set(keys))
    return body


def all_doses(body):
    return [dose for group in body["groups"] for dose in group["doses"]]


@dataclass
class HistoryData:
    db: object
    make: object
    client: object
    auth: object
    patient: object
    now: datetime = DAY + timedelta(hours=13, minutes=1)

    def medication(self, mid=None, *, mode="theo_gio"):
        if mid is None:
            mid = self.make.catalog_medication(name="Integration medicine")
        prescription = self.db.execute(
            text(
                "INSERT INTO prescriptions (user_id,entry_source) "
                "VALUES (:p,'thu_cong') RETURNING id"
            ),
            {"p": self.patient},
        ).scalar_one()
        uid = self.db.execute(
            text(
                "INSERT INTO user_medications (user_id,prescription_id,medication_id,entry_method,"
                "quantity_per_dose,doses_per_day,dosing_mode) "
                "VALUES (:p,:rx,:m,'thu_cong',1,1,CAST(:mode AS medication_dosing_mode)) "
                "RETURNING id"
            ),
            {"p": self.patient, "rx": prescription, "m": mid, "mode": mode},
        ).scalar_one()
        return uid, mid

    def schedule(
        self,
        at=None,
        *,
        medication=None,
        effective=None,
        ended=None,
        weekdays=(1, 2, 3, 4, 5, 6, 7),
        reminder=True,
    ):
        at = at if at is not None else DAY + timedelta(hours=8)
        uid, mid = medication if medication is not None else self.medication()
        sid = self.db.execute(
            text(
                "INSERT INTO medication_schedules (user_medication_id,intake_time,days_of_week,"
                "reminder_enabled,effective_from,ended_at) "
                "VALUES (:u,:t,:days,:r,:f,:e) RETURNING id"
            ),
            {
                "u": uid,
                "t": at.time(),
                "days": list(weekdays),
                "r": reminder,
                "f": effective
                if effective is not None
                else at.replace(hour=0, minute=0, second=0, microsecond=0),
                "e": ended,
            },
        ).scalar_one()
        return SimpleNamespace(
            schedule_id=sid,
            patient_id=self.patient,
            scheduled_at=at,
            user_medication_id=uid,
            medication_id=mid,
        )

    def log(self, schedule, status="bo_lo", taken=None):
        if status != "bo_lo" and taken is None:
            taken = schedule.scheduled_at
        return self.db.execute(
            text(
                "INSERT INTO dose_logs (medication_schedule_id,scheduled_at,taken_at,status) "
                "VALUES (:s,:at,:taken,CAST(:st AS dose_status)) RETURNING id"
            ),
            {"s": schedule.schedule_id, "at": schedule.scheduled_at, "taken": taken, "st": status},
        ).scalar_one()

    def sync(self, at):
        """Checkpoint đồng bộ của patient (3.19); giờ do test chọn."""
        self.db.execute(
            text(
                "INSERT INTO dose_sync_checkpoints (user_id, synced_at) VALUES (:u, :t) "
                "ON CONFLICT (user_id) DO UPDATE SET synced_at = EXCLUDED.synced_at"
            ),
            {"u": self.patient, "t": at},
        )

    def unsync(self):
        self.db.execute(
            text("DELETE FROM dose_sync_checkpoints WHERE user_id = :u"), {"u": self.patient}
        )

    def snapshot(self):
        return self.db.execute(
            text(
                "SELECT dl.* FROM dose_logs dl JOIN medication_schedules ms "
                "ON ms.id=dl.medication_schedule_id JOIN user_medications um "
                "ON um.id=ms.user_medication_id WHERE um.user_id=:p ORDER BY dl.id"
            ),
            {"p": self.patient},
        ).all()

    def read(self, **params):
        return self.client.get("/adherence", params=params, headers=self.auth(self.patient))

    def day(self, **params):
        return self.read(**{"from": DAY.date().isoformat(), "to": DAY.date().isoformat(), **params})

    def confirm(self, schedule, taken, cid=None):
        item = {
            "client_uuid": str(cid or uuid4()),
            "schedule_id": schedule.schedule_id,
            "scheduled_at": schedule.scheduled_at.isoformat(),
            "taken_at": taken.isoformat(),
        }
        response = self.client.post("/doses/batch", json=[item], headers=self.auth(self.patient))
        assert response.status_code == 200 and response.json()["summary"]["failed"] == 0
        return item


@pytest.fixture
def history_data(db, make, client, auth, monkeypatch):
    data = HistoryData(db, make, client, auth, make.user())
    data.sync(FULLY_SYNCED)
    monkeypatch.setattr(history_http, "now", lambda: data.now)
    monkeypatch.setattr(dose_http, "now", lambda: data.now)
    return data


def test_patient_history_by_date_medication_groups_and_80_percent__AC1_AC3_AC4(history_data):
    data = history_data
    same = data.make.catalog_medication(name="Same display name")
    other = data.make.catalog_medication(name="Same display name")
    entry = data.medication(same)
    for hour in (6, 7, 8):
        data.log(data.schedule(DAY + timedelta(hours=hour), medication=entry), "da_uong")
    late = data.schedule(DAY + timedelta(hours=9), medication=data.medication(same))
    data.log(late, "uong_tre", DAY + timedelta(hours=10))
    data.schedule(DAY + timedelta(hours=10), medication=data.medication(other))
    before = data.snapshot()
    by_date = assert_contract(data.day())
    assert by_date["summary"] == dict(
        total=5, taken=3, late=1, missed=1, pending=0, unverified=0, counted=5, adherence_rate=80
    )
    assert len(by_date["groups"]) == 1 and by_date["groups"][0]["date"] == "2026-10-19"
    by_med = assert_contract(data.day(group_by="medication"))
    assert [g["medication_id"] for g in by_med["groups"]] == sorted([same, other])
    assert [g["summary"]["total"] for g in by_med["groups"]] == [4, 1]
    assert by_med["summary"] == by_date["summary"]
    assert [g["summary"]["adherence_rate"] for g in by_med["groups"]] == [100, 0]
    assert data.snapshot() == before
    logs = data.make.access_logs(data.patient)
    assert len(logs) == 2 and all(log["result"] == "allowed" for log in logs)


def test_default_partial_and_inclusive_90_day_filters__AC5(history_data):
    data = history_data
    data.schedule(effective=DAY - timedelta(days=89))
    default = assert_contract(data.read())
    assert (default["from"], default["to"], default["summary"]["total"]) == (
        "2026-09-20",
        "2026-10-19",
        30,
    )
    full = assert_contract(data.read(**{"from": (DAY - timedelta(days=89)).date().isoformat()}))
    assert full["summary"]["total"] == 90
    assert [g["date"] for g in full["groups"]] == sorted(
        [g["date"] for g in full["groups"]], reverse=True
    )
    to_only = assert_contract(data.read(to="2026-10-14"))
    assert (to_only["from"], to_only["to"], to_only["summary"]["total"]) == (
        "2026-09-15",
        "2026-10-14",
        30,
    )
    from_only = assert_contract(data.read(**{"from": "2026-10-15"}))
    assert from_only["summary"]["total"] == 5
    invalid = data.read(**{"from": (DAY - timedelta(days=90)).date().isoformat()})
    assert invalid.status_code == 422 and invalid.json() == {"detail": "adherence_range_too_large"}


@pytest.mark.parametrize(
    "query",
    [
        {"from": "2026-02-30"},
        {"from": "20261019"},
        {"from": "2026-10-19T00:00:00"},
        {"from": "2026-10-19", "to": "2026-10-18"},
        {"to": "2026-10-20"},
        {"group_by": "other"},
        {"patient_id": "invalid-uuid"},
    ],
)
def test_bad_queries_are_422_without_health_payload__AC14(history_data, query):
    response = history_data.read(**query)
    assert response.status_code == 422
    assert set(response.json()) == {"detail"}
    assert response.headers["cache-control"] == "no-store"
    assert history_data.snapshot() == []


def test_empty_and_pending_only_have_null_rate__AC8(history_data):
    data = history_data
    empty = assert_contract(data.day())
    assert empty["groups"] == [] and empty["summary"] == dict(
        total=0, taken=0, late=0, missed=0, pending=0, unverified=0, counted=0, adherence_rate=None
    )
    data.schedule()
    data.now = DAY + timedelta(hours=8)
    body = assert_contract(data.day())
    assert body["summary"]["pending"] == 1 and body["summary"]["adherence_rate"] is None
    assert len(all_doses(body)) == 1


@pytest.mark.parametrize(
    "elapsed,pending",
    [
        (timedelta(minutes=10), True),
        (timedelta(minutes=30), True),
        (timedelta(minutes=30, microseconds=1), True),
        (timedelta(minutes=120), True),
        (timedelta(minutes=120, microseconds=1), False),
    ],
)
def test_unconfirmed_30_120_boundaries_without_writes__AC7(history_data, elapsed, pending):
    data = history_data
    occurrence = data.schedule()
    before = data.snapshot()
    data.now = occurrence.scheduled_at + elapsed
    body = assert_contract(data.day())
    dose = all_doses(body)[0]
    assert dose["status"] == ("cho_xac_nhan" if pending else "bo_lo")
    assert dose["status_source"] == "inferred" and dose["taken_at"] is None
    assert body["summary"]["counted"] == (0 if pending else 1)
    assert data.snapshot() == before


def test_worker_missing_log_120_and_after_changes_rate_without_writes__AC16(history_data):
    data = history_data
    data.log(data.schedule(), "da_uong")
    data.schedule(DAY + timedelta(hours=10))
    before = data.snapshot()
    data.now = DAY + timedelta(hours=12)
    deadline = assert_contract(data.day())
    assert (
        deadline["summary"]["pending"],
        deadline["summary"]["counted"],
        deadline["summary"]["adherence_rate"],
    ) == (1, 1, 100)
    data.now += timedelta(minutes=1)
    after = assert_contract(data.day())
    assert (
        after["summary"]["missed"],
        after["summary"]["counted"],
        after["summary"]["adherence_rate"],
    ) == (1, 2, 50)
    assert data.snapshot() == before and len(data.make.access_logs(data.patient)) == 2


def test_legacy_early_missed_pending_through_deadline_without_rewrite__AC21(history_data):
    data = history_data
    occurrence = data.schedule()
    data.log(occurrence)
    data.log(data.schedule(DAY + timedelta(hours=9)), "da_uong")
    before = data.snapshot()
    for elapsed in (
        timedelta(minutes=60),
        timedelta(minutes=90),
        timedelta(minutes=120),
        timedelta(minutes=120, microseconds=1),
    ):
        data.now = occurrence.scheduled_at + elapsed
        body = assert_contract(data.day())
        dose = next(d for d in all_doses(body) if d["schedule_id"] == occurrence.schedule_id)
        pending = elapsed <= timedelta(minutes=120)
        assert (dose["status"], dose["status_source"]) == (
            ("cho_xac_nhan", "inferred") if pending else ("bo_lo", "recorded")
        )
        assert body["summary"]["taken"] == 1
    assert data.snapshot() == before


def test_recorded_confirmation_boundaries_and_late_sync_use_taken_at__AC17(history_data):
    data = history_data
    delays = [timedelta(minutes=30), timedelta(minutes=30, microseconds=1), timedelta(minutes=120)]
    for hour, delay in zip((8, 9, 10), delays, strict=True):
        occurrence = data.schedule(DAY + timedelta(hours=hour))
        data.confirm(occurrence, occurrence.scheduled_at + delay)
    body = assert_contract(data.day())
    assert [d["status"] for d in all_doses(body)] == ["da_uong", "uong_tre", "uong_tre"]
    assert body["summary"]["adherence_rate"] == 100
    assert all_doses(body)[1]["taken_at"] == "2026-10-19T09:30:00.000001+07:00"
    data.now += timedelta(hours=4)
    assert all_doses(assert_contract(data.day())) == all_doses(body)


def test_early_confirmation_is_excluded_until_scheduled_time__AC6_AC18(history_data):
    data = history_data
    occurrence = data.schedule(effective=DAY + timedelta(hours=7, minutes=50))
    data.confirm(occurrence, DAY + timedelta(hours=7, minutes=40))
    data.now = DAY + timedelta(hours=7, minutes=59)
    assert assert_contract(data.day())["summary"]["total"] == 0
    data.now = DAY + timedelta(hours=8)
    body = assert_contract(data.day())
    assert body["summary"]["taken"] == 1
    assert all_doses(body)[0]["taken_at"] == "2026-10-19T07:40:00+07:00"


def test_scheduled_date_across_midnight_and_date_order__AC9(history_data):
    data = history_data
    occurrence = data.schedule(DAY + timedelta(hours=23, minutes=30), ended=DAY + timedelta(days=1))
    taken = DAY + timedelta(days=1, minutes=10)
    data.log(occurrence, "uong_tre", taken)
    data.now = DAY + timedelta(days=1, hours=1)
    data.schedule(DAY + timedelta(days=1))
    narrow = assert_contract(data.day())
    assert len(all_doses(narrow)) == 1 and narrow["groups"][0]["date"] == "2026-10-19"
    assert all_doses(narrow)[0]["taken_at"] == "2026-10-20T00:10:00+07:00"
    wide = assert_contract(data.read(**{"from": "2026-10-19", "to": "2026-10-20"}))
    assert [g["date"] for g in wide["groups"]] == ["2026-10-20", "2026-10-19"]


def test_schedule_versions_stop_soft_delete_as_needed_and_reminder_history__AC10_AC18_AC19(
    history_data,
):
    data = history_data
    med = data.medication()
    data.schedule(
        DAY + timedelta(hours=8),
        medication=med,
        effective=DAY - timedelta(days=59),
        ended=DAY - timedelta(days=40),
    )
    data.schedule(
        DAY + timedelta(hours=9),
        medication=med,
        effective=DAY - timedelta(days=40),
        ended=DAY - timedelta(days=30),
    )
    data.db.execute(
        text(
            "UPDATE user_medications SET ended_at=:e,deleted_at=:d,dosing_mode='khi_can' "
            "WHERE id=:u"
        ),
        {"u": med[0], "e": DAY - timedelta(days=30), "d": DAY},
    )
    data.db.execute(
        text("UPDATE medications SET deleted_at=:d WHERE id=:m"), {"m": med[1], "d": DAY}
    )
    data.medication(mode="khi_can")  # No historical schedule, hence no compulsory occurrence.
    active = data.schedule()
    query = {"from": (DAY - timedelta(days=60)).date().isoformat(), "to": DAY.date().isoformat()}
    before = assert_contract(data.read(**query))
    old = [d for d in all_doses(before) if d["medication_id"] == med[1]]
    assert len(old) == 29
    assert {datetime.fromisoformat(d["scheduled_at"]).hour for d in old} == {8, 9}
    assert max(d["scheduled_at"] for d in old) < (DAY - timedelta(days=30)).isoformat()
    assert before["summary"]["total"] == 30
    data.db.execute(
        text("UPDATE medication_schedules SET reminder_enabled=false WHERE id=:s"),
        {"s": active.schedule_id},
    )
    assert assert_contract(data.read(**query)) == before


@pytest.mark.parametrize(
    "start_delta,end_delta,weekday,due",
    [
        (-1, None, None, True),
        (0, None, None, True),
        (1, None, None, False),
        (-1, 0, None, False),
        (-1, 1, None, True),
        (-1, None, 2, False),
    ],
)
def test_occurrence_effective_bounds_and_weekdays__AC18(
    history_data, start_delta, end_delta, weekday, due
):
    data = history_data
    at = DAY + timedelta(hours=8)
    data.schedule(
        at,
        effective=at + timedelta(microseconds=start_delta),
        ended=None if end_delta is None else at + timedelta(microseconds=end_delta),
        weekdays=(weekday,) if weekday is not None else (DAY.isoweekday(),),
    )
    assert assert_contract(data.day())["summary"]["total"] == int(due)


def scanner_ports(data, occurrences):
    # Occurrences/context/cursor/devices are controlled; permission facts,
    # transactions, unique constraints, dose writes and notification writes are real.
    context = {
        (occ.schedule_id, occ.patient_id): "Integration medicine" for occ in occurrences
    }

    def alert_context(uow, schedule_id, patient_id):
        return context.get((schedule_id, patient_id))

    return dict(
        now=data.now,
        grace=timedelta(minutes=120),
        overlap=timedelta(minutes=30),
        cursor=Mock(get=Mock(return_value=None)),
        schedules=Mock(
            occurrences_between=Mock(return_value=occurrences),
            alert_context=Mock(side_effect=alert_context),
        ),
        dose_logs=SqlDoseLogs(),
        access=AccessGuardAdapter(),
        tokens=Mock(android_tokens=Mock(return_value=[])),
        notifications=SqlNotifications(),
        checkpoints=SqlSyncCheckpoints(),
        pending=SqlPendingVerifications(LATE_CONFIRMATION_WINDOW),
    )


def notification_count(data):
    return data.db.execute(
        text("SELECT count(*) FROM notifications WHERE about_patient_user_id=:p"),
        {"p": data.patient},
    ).scalar_one()


def test_worker_window_notifications_use_strict_120_and_preserve_confirmed__AC22(
    history_data, role_engines
):
    data = history_data
    data.make.family_of(data.patient)
    data.now = DAY + timedelta(hours=12)
    pending = data.schedule(data.now - timedelta(minutes=30))
    deadline = data.schedule(data.now - timedelta(minutes=120))
    expired = data.schedule(data.now - timedelta(minutes=120, microseconds=1))
    confirmed = data.schedule(data.now - timedelta(minutes=121))
    data.log(confirmed, "da_uong")
    occurrences = [pending, deadline, expired, confirmed]
    for _ in range(2):
        with role_engines["worker_role"].begin() as connection:
            scan(SqlUnitOfWork(connection), **scanner_ports(data, occurrences))
    rows = data.snapshot()
    assert len(rows) == 2
    statuses = {r.medication_schedule_id: str(r.status) for r in rows}
    assert statuses == {expired.schedule_id: "bo_lo", confirmed.schedule_id: "da_uong"}
    assert notification_count(data) == 1
    body = assert_contract(data.day())
    assert body["summary"]["pending"] == 2
    assert body["summary"]["taken"] == body["summary"]["missed"] == 1


def test_api_role_cannot_create_worker_notifications(history_data, role_engines):
    data = history_data
    data.make.family_of(data.patient)
    occurrence = data.schedule()
    with pytest.raises(ProgrammingError, match="permission denied for table notifications"):
        with role_engines["api_role"].begin() as connection:
            scan(SqlUnitOfWork(connection), **scanner_ports(data, [occurrence]))
    assert data.snapshot() == [] and notification_count(data) == 0


@pytest.mark.parametrize("minutes", [30, 60, 180])
def test_wrong_worker_window_has_no_dose_or_notification_writes__AC22(history_data, minutes):
    data = history_data
    data.make.family_of(data.patient)
    occurrence = data.schedule()
    args = scanner_ports(data, [occurrence])
    args["grace"] = timedelta(minutes=minutes)
    with get_engine().begin() as connection:
        with pytest.raises(ValueError, match="must_be_120"):
            scan(SqlUnitOfWork(connection), **args)
    assert data.snapshot() == [] and notification_count(data) == 0


def test_late_sync_worker_log_and_retry_keep_one_occurrence__AC15_AC20(history_data):
    data = history_data
    occurrence = data.schedule()
    first = assert_contract(data.day())
    assert (all_doses(first)[0]["status"], all_doses(first)[0]["status_source"]) == (
        "bo_lo",
        "inferred",
    )
    data.log(occurrence)
    second = assert_contract(data.day())
    assert (
        second["summary"] == first["summary"]
        and all_doses(second)[0]["status_source"] == "recorded"
    )
    item = data.confirm(occurrence, occurrence.scheduled_at + timedelta(minutes=90))
    response = data.client.post("/doses/batch", json=[item], headers=data.auth(data.patient))
    assert response.status_code == 200 and response.json()["summary"]["synced"] == 1
    final = assert_contract(data.day())
    assert final["summary"]["total"] == 1 and final["summary"]["late"] == 1
    assert final["summary"]["adherence_rate"] == 100
    assert len(data.snapshot()) == 1


@pytest.mark.parametrize("first_writer", ["worker", "confirmation"])
def test_worker_insert_races_with_valid_late_confirmation__AC15_AC20_AC22(
    history_data, role_engines, first_writer
):
    data = history_data
    data.make.family_of(data.patient)
    occurrence = data.schedule()
    data.now = occurrence.scheduled_at + timedelta(minutes=121)
    cid = uuid4()
    taken = occurrence.scheduled_at + timedelta(minutes=90)
    confirmation = DoseConfirmation(cid, occurrence.schedule_id, occurrence.scheduled_at, taken)
    worker_engine = role_engines["worker_role"]
    held_engine = worker_engine if first_writer == "worker" else get_engine()
    held = held_engine.connect()
    transaction = held.begin()

    def worker():
        with worker_engine.begin() as connection:
            scan(SqlUnitOfWork(connection), **scanner_ports(data, [occurrence]))

    def confirm():
        data.confirm(occurrence, taken, cid)

    try:
        if first_writer == "worker":
            scan(SqlUnitOfWork(held), **scanner_ports(data, [occurrence]))
            contender = confirm
        else:
            result = confirm_doses(
                SqlUnitOfWork(held),
                caller_id=data.patient,
                caller_is_admin=False,
                items=[confirmation],
                now=data.now,
                access=AccessGuardAdapter(),
                schedules=SchedulesAdapter(),
                dose_logs=SqlDoseLogs(),
            )
            assert result.failed == 0
            contender = worker
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(contender)
            try:
                contender_role = "api_role" if first_writer == "worker" else "worker_role"
                deadline = monotonic() + 20
                while monotonic() < deadline:
                    waiting = data.db.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE usename=:role "
                            "AND wait_event_type='Lock'"
                        ),
                        {"role": contender_role},
                    ).scalar_one()
                    if waiting:
                        break
                else:
                    raise AssertionError("contending writer never waited for the unique-key lock")
                transaction.commit()
            finally:
                if transaction.is_active:
                    transaction.rollback()
            future.result(timeout=20)
    finally:
        if transaction.is_active:
            transaction.rollback()
        held.close()
    data.confirm(occurrence, taken, cid)
    rows = data.snapshot()
    assert len(rows) == 1 and str(rows[0].status) == "uong_tre"
    assert rows[0].taken_at == taken
    assert notification_count(data) == (1 if first_writer == "worker" else 0)
    body = assert_contract(data.day())
    assert body["summary"]["total"] == body["summary"]["late"] == 1


def test_single_history_select_is_consistent_during_committed_updates__AC3_AC4_AC20(history_data):
    data = history_data
    first = data.schedule(DAY + timedelta(hours=8))
    second = data.schedule(DAY + timedelta(hours=9))
    for occurrence in (first, second):
        data.log(occurrence)
    statements = []

    def update_after_history_select(conn, cursor, statement, parameters, context, executemany):
        if "WITH patient_schedules AS" not in statement:
            return
        statements.append(statement)
        data.db.execute(
            text(
                "UPDATE dose_logs SET status='da_uong',taken_at=scheduled_at "
                "WHERE medication_schedule_id=ANY(:ids)"
            ),
            {"ids": [first.schedule_id, second.schedule_id]},
        )

    engine = get_engine()
    event.listen(engine, "after_cursor_execute", update_after_history_select)
    try:
        before = assert_contract(data.day())
    finally:
        event.remove(engine, "after_cursor_execute", update_after_history_select)
    assert len(statements) == 1
    assert before["summary"]["missed"] == 2 and before["summary"]["adherence_rate"] == 0
    assert {d["status"] for d in all_doses(before)} == {"bo_lo"}
    after = assert_contract(data.day())
    assert after["summary"]["taken"] == 2 and after["summary"]["adherence_rate"] == 100


def _family_read(data, family):
    return data.client.get(
        "/adherence",
        params={
            "from": DAY.date().isoformat(),
            "to": DAY.date().isoformat(),
            "patient_id": str(data.patient),
        },
        headers=data.auth(family),
    )


def test_unverified_and_last_synced__AC40(history_data):
    data = history_data
    data.unsync()
    family = data.make.family_of(data.patient)
    occurrence = data.schedule()  # 08:00, hạn chót 10:00
    data.log(data.schedule(DAY + timedelta(hours=7)), "da_uong")
    data.now = DAY + timedelta(hours=12)
    for synced, expected_synced in (
        (None, None),
        (DAY + timedelta(hours=9, minutes=59, seconds=59), "2026-10-19T09:59:59+07:00"),
    ):
        if synced is not None:
            data.sync(synced)
        for response in (data.day(), _family_read(data, family)):
            body = assert_contract(response)
            dose = next(d for d in all_doses(body) if d["schedule_id"] == occurrence.schedule_id)
            assert (dose["status"], dose["status_source"], dose["taken_at"]) == (
                "chua_xac_minh",
                "inferred",
                None,
            )
            summary = body["summary"]
            assert (summary["unverified"], summary["pending"], summary["counted"]) == (1, 0, 1)
            assert summary["missed"] == 0 and summary["adherence_rate"] == 100
            assert body["patient_last_synced_at"] == expected_synced
    logs = data.make.access_logs(data.patient)
    assert [(log["actor_role"], log["result"]) for log in logs] == [
        ("patient", "allowed"),
        ("family", "allowed"),
    ] * 2
    assert data.snapshot()[0].status == "da_uong" and len(data.snapshot()) == 1


@pytest.mark.parametrize("reminder", [True, False])
def test_inferred_missed_after_checkpoint__AC40(history_data, reminder):
    data = history_data
    data.unsync()
    occurrence = data.schedule(reminder=reminder)
    data.now = DAY + timedelta(hours=12)
    data.sync(occurrence.scheduled_at + LATE_CONFIRMATION_WINDOW)  # cp = D đúng
    body = assert_contract(data.day())
    dose = all_doses(body)[0]
    assert (dose["status"], dose["status_source"]) == ("bo_lo", "inferred")
    assert body["summary"]["unverified"] == 0 and body["summary"]["missed"] == 1
    assert body["patient_last_synced_at"] == "2026-10-19T10:00:00+07:00"
    assert data.snapshot() == []


def test_recorded_after_worker__AC40(history_data):
    data = history_data
    data.unsync()
    occurrence = data.schedule()
    data.now = DAY + timedelta(hours=12)
    assert all_doses(assert_contract(data.day()))[0]["status"] == "chua_xac_minh"
    data.log(occurrence)  # Worker đã ghi sau khi xác minh
    dose = all_doses(assert_contract(data.day()))[0]
    assert (dose["status"], dose["status_source"]) == ("bo_lo", "recorded")
