"""Task 3.19: Worker chỉ ghi bo_lo khi đã xác minh (checkpoint >= hạn chót), trên Postgres thật.

Worker chạy bằng worker_role với adapter SQL/PEP thật; clock cố định; push đi qua một notifier giả
ghi lại (FCM thật được thử thủ công, AC39/AC43). Lịch của test khác không lọt vào vì lượt quét
chỉ nhận lượt uống của patient trong test (SQL `occurrences_between` thật, lọc theo patient).
"""

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_adherence_history_api import DAY, HistoryData
from test_adherence_history_api import history_data as history_data

from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    DeviceTokensAdapter,
    PatientNamesAdapter,
    SchedulesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import (
    SqlDoseLogs,
    SqlNotifications,
    SqlPendingVerifications,
    SqlScanCursor,
    SqlSyncCheckpoints,
)
from drugtime.modules.adherence.application.scan_missed_doses import scan_and_notify
from drugtime.modules.adherence.domain.dose import LATE_CONFIRMATION_WINDOW
from drugtime.notification_gateway.fcm import build_fcm_payload
from drugtime.shared.db import SqlUnitOfWork

WINDOW = LATE_CONFIRMATION_WINDOW
L = DAY + timedelta(hours=8)  # 08:00 VN = 01:00Z
D = L + WINDOW  # hạn chót 10:00 VN
GENERIC_BODY = "Bạn có cảnh báo mới về người thân"


class MemoryCursor:
    def __init__(self, value=None):
        self.value = value

    def get(self, uow):
        return self.value

    def advance(self, uow, until):
        self.value = until


class OwnCursor(SqlScanCursor):
    """Cursor thật trên bảng missed_dose_scan_cursor nhưng job riêng, để kiểm rollback."""

    def __init__(self):
        self.JOB = f"test-3.19-{uuid4().hex}"


class OnlyPatients:
    """SQL occurrences_between thật, giữ lại lượt uống của patient trong test."""

    def __init__(self, patients):
        self.patients = set(patients)
        self.real = SchedulesAdapter()

    def occurrences_between(self, uow, start, end):
        return [
            o
            for o in self.real.occurrences_between(uow, start, end)
            if o.patient_id in self.patients
        ]

    def alert_context(self, uow, schedule_id, patient_id):
        return self.real.alert_context(uow, schedule_id, patient_id)


class FailingNotifications(SqlNotifications):
    def create_missed_alert(self, *args, **kwargs):
        raise RuntimeError("injected failure while creating notification")


@dataclass
class Pushes:
    alerts: list = field(default_factory=list)
    syncs: list = field(default_factory=list)

    def send(self, alerts):
        self.alerts += alerts
        return []

    def request_sync(self, requests):
        self.syncs += requests
        return []

    def alerts_to(self, token):
        return [a for a in self.alerts if a.device_token == token]

    def syncs_to(self, token):
        return [s for s in self.syncs if s.device_token == token]


@dataclass
class World:
    data: HistoryData
    worker: object
    cursor: object = field(default_factory=MemoryCursor)
    pushes: Pushes = field(default_factory=Pushes)
    patients: set = field(default_factory=set)

    def __post_init__(self):
        self.patients.add(self.data.patient)

    @property
    def db(self):
        return self.data.db

    @property
    def make(self):
        return self.data.make

    @property
    def patient(self):
        return self.data.patient

    def token(self, user, platform="android"):
        token = f"tok-{platform}-{uuid4().hex}"
        self.db.execute(
            text(
                "INSERT INTO device_tokens (user_id, fcm_token, platform) "
                "VALUES (:u, :t, CAST(:p AS device_platform))"
            ),
            {"u": user, "t": token, "p": platform},
        )
        return token

    def checkpoint(self, at, user=None):
        self.db.execute(
            text(
                "INSERT INTO dose_sync_checkpoints (user_id, synced_at) VALUES (:u, :t) "
                "ON CONFLICT (user_id) DO UPDATE SET synced_at = EXCLUDED.synced_at"
            ),
            {"u": user or self.patient, "t": at},
        )

    @contextmanager
    def _uow(self):
        with self.worker.begin() as connection:
            yield SqlUnitOfWork(connection)

    def run(self, now, *, notifications=None, cursor=None):
        return scan_and_notify(
            self._uow,
            self.pushes,
            now=now,
            grace=WINDOW,
            overlap=timedelta(minutes=30),
            cursor=cursor or self.cursor,
            schedules=OnlyPatients(self.patients),
            dose_logs=SqlDoseLogs(),
            access=AccessGuardAdapter(),
            tokens=DeviceTokensAdapter(),
            notifications=notifications or SqlNotifications(),
            checkpoints=SqlSyncCheckpoints(),
            pending=SqlPendingVerifications(WINDOW),
            patient_names=PatientNamesAdapter(),
        )

    def logs(self, patient=None):
        rows = self.db.execute(
            text(
                "SELECT dl.medication_schedule_id AS schedule_id, dl.scheduled_at, dl.taken_at, "
                "dl.status::text AS status FROM dose_logs dl JOIN medication_schedules ms "
                "ON ms.id = dl.medication_schedule_id JOIN user_medications um "
                "ON um.id = ms.user_medication_id WHERE um.user_id = :p ORDER BY dl.scheduled_at"
            ),
            {"p": patient or self.patient},
        )
        return [r._asdict() for r in rows]

    def notifications(self, family, patient=None):
        rows = self.db.execute(
            text(
                "SELECT id, medication_name, scheduled_at, content FROM notifications "
                "WHERE user_id = :f AND about_patient_user_id = :p ORDER BY scheduled_at, id"
            ),
            {"f": family, "p": patient or self.patient},
        )
        return [r._asdict() for r in rows]

    def pending(self, patient=None):
        return self.db.execute(
            text(
                "SELECT medication_schedule_id, scheduled_at "
                "FROM missed_dose_pending_verifications "
                "WHERE patient_user_id = :p ORDER BY scheduled_at"
            ),
            {"p": patient or self.patient},
        ).all()

    def access_log_count(self, patient=None):
        return self.db.execute(
            text("SELECT count(*) FROM access_logs WHERE patient_user_id = :p"),
            {"p": patient or self.patient},
        ).scalar_one()


@pytest.fixture
def world(history_data, role_engines):
    history_data.unsync()  # fixture 3.23 coi patient đã đồng bộ; test 3.19 bắt đầu chưa đồng bộ
    return World(history_data, role_engines["worker_role"])


@pytest.fixture
def family_world(world):
    """Patient P, người thân F có liên kết + chia sẻ, mỗi người một token Android."""
    world.family = world.make.family_of(world.patient)
    world.family_token = world.token(world.family)
    world.patient_token = world.token(world.patient)
    return world


def assert_verified_alert(w, occ, *, pushes=1):
    logs = [r for r in w.logs() if r["schedule_id"] == occ.schedule_id]
    assert len(logs) == 1
    assert logs[0]["status"] == "bo_lo" and logs[0]["taken_at"] is None
    items = [n for n in w.notifications(w.family) if n["scheduled_at"] == occ.scheduled_at]
    assert len(items) == 1
    assert items[0]["medication_name"] == "Integration medicine"
    alerts = [a for a in w.pushes.alerts_to(w.family_token) if a.notification_id == items[0]["id"]]
    assert len(alerts) == pushes


def test_verified_missed_creates_one_log_notification_push__AC17(family_world):
    w = family_world
    occ = w.data.schedule(L)
    w.checkpoint(D + timedelta(minutes=5))
    audit_before = w.access_log_count()
    w.run(D + timedelta(minutes=6))
    assert_verified_alert(w, occ)
    assert w.pending() == []
    assert w.pushes.syncs_to(w.patient_token) == []
    assert w.access_log_count() == audit_before


@pytest.mark.parametrize("cp", [None, D - timedelta(seconds=1)])
def test_checkpoint_before_deadline_no_effect__AC18(family_world, cp):
    w = family_world
    occ = w.data.schedule(L)
    if cp is not None:
        w.checkpoint(cp)
    w.run(D + timedelta(minutes=1))
    assert w.logs() == [] and w.notifications(w.family) == []
    assert w.pushes.alerts_to(w.family_token) == []
    assert [(p.medication_schedule_id, p.scheduled_at) for p in w.pending()] == [
        (occ.schedule_id, L)
    ]
    assert len(w.pushes.syncs_to(w.patient_token)) == 1


def test_late_checkpoint_verifies_after_cursor_passed__AC19(family_world):
    w = family_world
    occ = w.data.schedule(L)
    for hours in (1, 4, 6):  # 10:01, 13:01, 15:01 VN: cursor đi qua L, P vẫn chưa đồng bộ
        w.run(D + timedelta(hours=hours - 1, minutes=1))
    assert w.cursor.value > L + timedelta(minutes=30)
    assert w.logs() == [] and len(w.pending()) == 1
    assert len(w.pushes.syncs_to(w.patient_token)) == 1  # chỉ gõ khi liều vừa vào hàng chờ
    w.checkpoint(DAY + timedelta(hours=15))
    w.run(DAY + timedelta(hours=15, minutes=15))
    assert_verified_alert(w, occ)
    assert w.pending() == []


def test_late_confirmation_then_checkpoint_never_alerts__AC20(family_world):
    w = family_world
    occ = w.data.schedule(L)
    w.run(D + timedelta(minutes=1))
    assert len(w.pending()) == 1
    w.data.now = DAY + timedelta(hours=15)
    w.data.confirm(occ, L + timedelta(minutes=10))
    w.checkpoint(DAY + timedelta(hours=15))
    w.run(DAY + timedelta(hours=15, minutes=15))
    logs = w.logs()
    assert len(logs) == 1 and logs[0]["status"] == "da_uong"
    assert w.notifications(w.family) == [] and w.pushes.alerts_to(w.family_token) == []
    assert w.pending() == []


@pytest.mark.parametrize(
    "cp,verified",
    [(D, True), (D - timedelta(microseconds=1), False)],
)
def test_checkpoint_boundary_microsecond__AC21(family_world, cp, verified):
    w = family_world
    occ = w.data.schedule(L)
    w.checkpoint(cp)
    w.run(D + timedelta(minutes=1))
    if verified:
        assert_verified_alert(w, occ)
    else:
        assert w.logs() == [] and len(w.pending()) == 1


def test_now_equal_deadline__AC22(family_world):
    w = family_world
    occ = w.data.schedule(L)
    w.checkpoint(D + timedelta(minutes=5))
    w.run(D)
    assert w.logs() == [] and w.pending() == [] and w.pushes.syncs == [] and w.pushes.alerts == []
    w.run(D + timedelta(seconds=1))
    assert_verified_alert(w, occ)


def test_confirmed_before_deadline__AC23(family_world):
    w = family_world
    occ = w.data.schedule(L)
    w.data.now = L + timedelta(minutes=10)
    w.data.confirm(occ, L + timedelta(minutes=10))
    before = w.logs()
    w.checkpoint(D + timedelta(minutes=5))
    w.run(D + timedelta(minutes=6))
    assert w.logs() == before and before[0]["status"] == "da_uong"
    assert w.notifications(w.family) == [] and w.pending() == []
    assert w.pushes.syncs_to(w.patient_token) == [] and w.pushes.alerts_to(w.family_token) == []


def test_overlapping_scans_single_effect__AC24(family_world):
    w = family_world
    occ = w.data.schedule(L)
    w.checkpoint(D + timedelta(minutes=5))
    for minutes in (6, 7, 20):
        w.run(D + timedelta(minutes=minutes))
    assert_verified_alert(w, occ, pushes=1)
    assert len(w.pushes.alerts_to(w.family_token)) == 1


def _no_permission_family(w, case):
    make, patient = w.make, w.patient
    if case == "sharing_off":
        return make.family_of(patient, sharing=False)
    if case == "family_sharing_revoked":
        family = make.family_of(patient)
        make.revoke_consent(patient, "family_sharing")
        return family
    make.consent(patient, "family_sharing")
    family = make.user()
    if case == "pending":
        make.pending_link(patient, family)
    elif case == "revoked":
        make.link(patient, family, status="revoked", sharing=False)
    return family


@pytest.mark.parametrize(
    "case", ["sharing_off", "family_sharing_revoked", "pending", "revoked", "no_link"]
)
def test_recipient_without_permission_gets_nothing__AC28(world, case):
    w = world
    family = _no_permission_family(w, case)
    token = w.token(family)
    occ = w.data.schedule(L)
    w.checkpoint(D + timedelta(minutes=5))
    w.run(D + timedelta(minutes=6))
    assert [(r["schedule_id"], r["status"]) for r in w.logs()] == [(occ.schedule_id, "bo_lo")]
    assert w.notifications(family) == [] and w.pushes.alerts_to(token) == []


def test_permission_lost_between_pending_and_verification__AC28(family_world):
    w = family_world
    occ = w.data.schedule(L)
    w.run(D + timedelta(minutes=1))
    assert len(w.pending()) == 1
    w.db.execute(
        text(
            "UPDATE caregiver_links SET status = 'revoked', sharing_enabled = false, "
            "revoked_at = now() WHERE patient_user_id = :p AND family_user_id = :f"
        ),
        {"p": w.patient, "f": w.family},
    )
    w.checkpoint(DAY + timedelta(hours=11))
    w.run(DAY + timedelta(hours=11, minutes=15))
    assert [(r["schedule_id"], r["status"]) for r in w.logs()] == [(occ.schedule_id, "bo_lo")]
    assert w.notifications(w.family) == [] and w.pushes.alerts_to(w.family_token) == []


def test_ios_only_family_gets_inbox_without_push__AC29(world):
    w = world
    w.family = w.make.family_of(w.patient)
    ios = w.token(w.family, "ios")
    occ = w.data.schedule(L)
    w.checkpoint(D + timedelta(minutes=5))
    w.run(D + timedelta(minutes=6))
    assert [n["scheduled_at"] for n in w.notifications(w.family)] == [occ.scheduled_at]
    assert w.pushes.alerts_to(ios) == []


def test_three_meds_three_alerts__AC30(family_world):
    w = family_world
    occs = [w.data.schedule(L) for _ in range(3)]
    w.checkpoint(D + timedelta(minutes=5))
    w.run(D + timedelta(minutes=6))
    assert sorted(r["schedule_id"] for r in w.logs()) == sorted(o.schedule_id for o in occs)
    assert len(w.notifications(w.family)) == 3
    assert len({a.notification_id for a in w.pushes.alerts_to(w.family_token)}) == 3


def test_cursor_lag_backfill__AC31(family_world):
    w = family_world
    occs = [w.data.schedule(L + timedelta(hours=h)) for h in (0, 1, 2)]
    now = occs[-1].scheduled_at + WINDOW + timedelta(minutes=1)
    w.cursor = MemoryCursor(now - WINDOW - timedelta(hours=3))  # Worker sập 3 giờ
    w.checkpoint(now - timedelta(minutes=1))
    w.run(now)
    assert [(r["schedule_id"], r["status"]) for r in w.logs()] == [
        (o.schedule_id, "bo_lo") for o in occs
    ]
    assert len(w.notifications(w.family)) == 3


def test_failure_rolls_back_all__AC32(family_world):
    w = family_world
    cursor = OwnCursor()
    occ = w.data.schedule(L)
    w.run(D + timedelta(minutes=1), cursor=cursor)
    pending_before = w.pending()
    cursor_before = w.db.execute(
        text("SELECT scanned_until FROM missed_dose_scan_cursor WHERE job_name = :j"),
        {"j": cursor.JOB},
    ).scalar_one()
    w.checkpoint(DAY + timedelta(hours=11))
    w.pushes = Pushes()
    with pytest.raises(RuntimeError, match="injected failure"):
        w.run(
            DAY + timedelta(hours=11, minutes=15),
            cursor=cursor,
            notifications=FailingNotifications(),
        )
    assert w.logs() == [] and w.notifications(w.family) == []
    assert w.pending() == pending_before
    assert (
        w.db.execute(
            text("SELECT scanned_until FROM missed_dose_scan_cursor WHERE job_name = :j"),
            {"j": cursor.JOB},
        ).scalar_one()
        == cursor_before
    )
    assert w.pushes.alerts == [] and w.pushes.syncs == []
    w.run(DAY + timedelta(hours=11, minutes=30), cursor=cursor)
    assert_verified_alert(w, occ)


def test_stopped_or_deleted_medication_still_missed__AC33(family_world):
    w = family_world
    stopped = w.data.schedule(L, ended=DAY + timedelta(hours=9))
    deleted = w.data.schedule(L + timedelta(minutes=10), ended=DAY + timedelta(hours=9))
    w.db.execute(
        text("UPDATE user_medications SET ended_at = :t, deleted_at = :t WHERE id = :u"),
        {"t": DAY + timedelta(hours=9), "u": deleted.user_medication_id},
    )
    w.checkpoint(D + timedelta(minutes=15))
    w.run(D + timedelta(minutes=16))  # sau hạn chót của cả liều 08:10
    for occ in (stopped, deleted):
        assert_verified_alert(w, occ)


def test_too_early_confirmation_then_verified__AC34(family_world):
    w = family_world
    occ = w.data.schedule(L)
    w.data.now = L
    item = {
        "client_uuid": str(uuid4()),
        "schedule_id": occ.schedule_id,
        "scheduled_at": L.isoformat(),
        "taken_at": (L - timedelta(minutes=31)).isoformat(),
    }
    response = w.data.client.post("/doses/batch", json=[item], headers=w.data.auth(w.patient))
    assert response.status_code == 200
    result = response.json()["items"][0]
    assert result["result"] == "failed" and result["error"]["code"] == "taken_at_too_early"
    assert result["error"]["http_status"] == 422
    w.checkpoint(D + timedelta(minutes=5))
    w.run(D + timedelta(minutes=6))
    assert_verified_alert(w, occ)


def test_first_run_window_skips_old_deadlines__AC35(family_world):
    w = family_world
    w.data.schedule(L)
    w.checkpoint(D + timedelta(hours=1))
    w.run(D + timedelta(minutes=31))  # cursor rỗng: chỉ xét từ now - 120' - 30'
    assert w.logs() == [] and w.pending() == []
    assert w.pushes.alerts == [] and w.pushes.syncs == []


def test_offline_three_days_nine_alerts_generic_body__AC36(family_world):
    w = family_world
    first_day = DAY - timedelta(days=2)
    for hour in (8, 12, 16):
        w.data.schedule(first_day + timedelta(hours=hour))
    w.cursor = MemoryCursor(first_day + timedelta(hours=7))
    for day in range(3):
        w.run(first_day + timedelta(days=day, hours=19))
    assert len(w.pending()) == 9 and w.logs() == []
    w.checkpoint(DAY + timedelta(hours=20))
    w.pushes = Pushes()
    w.run(DAY + timedelta(hours=20, minutes=15))
    logs = w.logs()
    assert len(logs) == 9 and {r["status"] for r in logs} == {"bo_lo"}
    items = w.notifications(w.family)
    assert [n["scheduled_at"] for n in items] == [r["scheduled_at"] for r in logs]
    alerts = w.pushes.alerts_to(w.family_token)
    assert sorted(a.notification_id for a in alerts) == sorted(n["id"] for n in items)
    name = w.db.execute(
        text("SELECT full_name FROM users WHERE id = :p"), {"p": w.patient}
    ).scalar()
    assert name and all(name in n["content"] for n in items)  # hộp thư (sau PEP) có tên
    for alert in alerts:
        assert alert.body == GENERIC_BODY
        payload = json.dumps(build_fcm_payload(alert), ensure_ascii=False)
        assert name not in payload and "Integration medicine" not in payload
        assert "08:00" not in payload and "12:00" not in payload


def test_sync_request_android_only_once_per_token__AC37(family_world):
    w = family_world
    second_android = w.token(w.patient)
    ios = w.token(w.patient, "ios")
    for minutes in (0, 10, 20):
        w.data.schedule(L + timedelta(minutes=minutes))
    now = L + timedelta(minutes=20) + WINDOW + timedelta(minutes=1)
    w.run(now)
    assert len(w.pending()) == 3 and w.notifications(w.family) == []
    assert len(w.pushes.syncs_to(w.patient_token)) == 1
    assert len(w.pushes.syncs_to(second_android)) == 1
    assert w.pushes.syncs_to(ios) == []
    w.run(now + timedelta(minutes=15))  # chồng lấn: liều đã trong hàng chờ không gõ lại
    assert len(w.pushes.syncs_to(w.patient_token)) == 1


def test_verified_or_confirmed_doses_do_not_knock__AC37(family_world):
    w = family_world
    verified = w.data.schedule(L)
    confirmed = w.data.schedule(L)
    w.data.now = L + timedelta(minutes=5)
    w.data.confirm(confirmed, L + timedelta(minutes=5))
    w.checkpoint(D + timedelta(minutes=5))
    w.run(D + timedelta(minutes=6))
    assert w.pushes.syncs_to(w.patient_token) == []
    assert_verified_alert(w, verified)
