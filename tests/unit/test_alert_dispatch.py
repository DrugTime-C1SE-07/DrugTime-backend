from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.adherence.application.scan_missed_doses import scan
from drugtime.modules.adherence.domain.alert import Alert
from drugtime.notification_gateway.fcm import FcmGateway, build_fcm_payload


class FakeSchedules:
    def __init__(self, occurrences):
        self.occurrences = occurrences

    def occurrences_between(self, uow, start, until):
        return self.occurrences

    def alert_context(self, uow, schedule_id, patient_id):
        assert any(
            o.schedule_id == schedule_id and o.patient_id == patient_id for o in self.occurrences
        )
        return "Test medication"


def test_gateway_privacy_in_payload_and_failure_log(caplog, monkeypatch):
    gateway = FcmGateway("test-project", Mock(), Mock())
    secret = "unit-sensitive-device-token"
    alert = Alert(7, uuid4(), secret)

    def fail_send(_):
        raise RuntimeError(secret + " medication-name scheduled-time")

    monkeypatch.setattr(gateway, "_send_one", fail_send)
    gateway.send([alert])
    assert "notification 7" in caplog.text
    for value in (secret, "medication-name", "scheduled-time"):
        assert value not in caplog.text
    message = build_fcm_payload(alert)["message"]
    assert message["data"] == {"notification_id": "7"}
    assert message["android"]["notification"]["visibility"] == "PRIVATE"


class FakeDoseLogs:
    def __init__(self, missed_ids=None):
        self.missed_ids = missed_ids or {}

    def mark_missed(self, uow, schedule_id, scheduled_at):
        return self.missed_ids.get((schedule_id, scheduled_at))


class FakeAccessGuard:
    def __init__(self, caregivers=None):
        self.caregivers = caregivers or {}

    def caregivers_of(self, uow, patient_id):
        return self.caregivers.get(patient_id, [])


class FakeTokens:
    def __init__(self, android_tokens_map=None):
        # android_tokens_map: dict of user_id -> list of tokens
        self.android_tokens_map = android_tokens_map or {}

    def android_tokens(self, uow, user_ids):
        res = []
        for uid in user_ids:
            for tok in self.android_tokens_map.get(uid, []):
                res.append((uid, tok))
        return res


class FakeNotifications:
    def __init__(self):
        self.created = []
        self.next_id = 100

    def create_missed_alert(
        self,
        uow,
        recipient_id,
        patient_id,
        dedupe_key,
        content=None,
        *,
        medication_name,
        scheduled_at,
    ):
        assert medication_name == "Test medication"
        assert scheduled_at.utcoffset() is not None
        for _r_id, _p_id, k, _c, _nid in self.created:
            if k == dedupe_key:
                return None  # conflict / already exists
        self.next_id += 1
        self.created.append((recipient_id, patient_id, dedupe_key, content, self.next_id))
        return self.next_id


class FakeScanCursor:
    def __init__(self, initial=None):
        self.curr = initial
        self.advanced_to = None

    def get(self, uow):
        return self.curr

    def advance(self, uow, until):
        self.advanced_to = until


class FakePatientNames:
    def __init__(self, names=None):
        self.names = names or {}

    def get_patient_name(self, uow, patient_id):
        return self.names.get(patient_id)


class SyncedCheckpoints:
    """Mọi patient đã đồng bộ sau hạn chót: lượt quét đi nhánh đã xác minh (3.19)."""

    def get_many(self, uow, user_ids):
        return {u: datetime(9999, 1, 1, tzinfo=UTC) for u in user_ids}


class FakePending:
    def __init__(self):
        self.added = []

    def add(self, uow, occ):
        self.added.append(occ)
        return True

    def verified(self, uow, now):
        return []

    def remove(self, uow, occ):
        pass

    def purge_recorded(self, uow):
        pass


def scan_alerts(*args, **kwargs):
    return scan(*args, **kwargs).alerts


def test_dispatch_creates_alert_for_android_caregiver():
    # AC1: Bỏ lỡ liều, người thân có liên kết và token Android -> notification và Alert.
    patient_id = uuid4()
    caregiver_id = uuid4()
    scheduled_at = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)

    occ = SimpleNamespace(patient_id=patient_id, schedule_id=1, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    alerts = scan_alerts(
        None,
        now=datetime(2026, 10, 13, 11, 0, tzinfo=UTC),
        grace=timedelta(minutes=120),
        overlap=timedelta(minutes=30),
        cursor=FakeScanCursor(datetime(2026, 10, 13, 7, 0, tzinfo=UTC)),
        schedules=FakeSchedules([occ]),
        dose_logs=FakeDoseLogs({(1, scheduled_at): 999}),
        access=FakeAccessGuard({patient_id: [caregiver_id]}),
        tokens=FakeTokens({caregiver_id: ["token_android_123"]}),
        notifications=notifications,
        checkpoints=SyncedCheckpoints(),
        pending=FakePending(),
        patient_names=FakePatientNames({patient_id: "Nguyễn Văn A"}),
    )

    assert len(notifications.created) == 1
    assert notifications.created[0][0] == caregiver_id
    assert "Nguyễn Văn A" in notifications.created[0][3]

    assert len(alerts) == 1
    assert alerts[0].recipient_id == caregiver_id
    assert alerts[0].device_token == "token_android_123"
    # 3.19 Q10 (QD-26): thân push là câu chung; tên patient chỉ có trong hộp thư.
    assert alerts[0].body == "Bạn có cảnh báo mới về người thân"
    assert "Nguyễn Văn A" not in alerts[0].body


def test_dispatch_skips_push_for_ios_caregiver_but_creates_notification_row():
    # AC2: Người thân iOS có dòng notifications nhưng không có Alert push.
    patient_id = uuid4()
    caregiver_id = uuid4()
    scheduled_at = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)

    occ = SimpleNamespace(patient_id=patient_id, schedule_id=1, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    alerts = scan_alerts(
        None,
        now=datetime(2026, 10, 13, 11, 0, tzinfo=UTC),
        grace=timedelta(minutes=120),
        overlap=timedelta(minutes=30),
        cursor=FakeScanCursor(),
        schedules=FakeSchedules([occ]),
        dose_logs=FakeDoseLogs({(1, scheduled_at): 999}),
        access=FakeAccessGuard({patient_id: [caregiver_id]}),
        tokens=FakeTokens({}),  # iOS token bị filter ra, không có trong android_tokens
        notifications=notifications,
        checkpoints=SyncedCheckpoints(),
        pending=FakePending(),
        patient_names=FakePatientNames({patient_id: "Nguyễn Văn B"}),
    )

    # Dòng notification VẪN ĐƯỢC TẠO
    assert len(notifications.created) == 1
    assert notifications.created[0][0] == caregiver_id

    # Nhưng KHÔNG CÓ Alert push nào được phát sinh
    assert len(alerts) == 0


def test_dispatch_deduplicates_repeated_missed_dose_scans():
    # AC3: Cùng liều đã quét và đã tạo notification -> lượt quét sau không tạo lại và không gửi lặp
    patient_id = uuid4()
    caregiver_id = uuid4()
    scheduled_at = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)

    occ = SimpleNamespace(patient_id=patient_id, schedule_id=1, scheduled_at=scheduled_at)
    notifications = FakeNotifications()
    # Giả sử đã có một bản ghi với dedupe_key này
    notifications.created.append(
        (caregiver_id, patient_id, "bo_lo:999:" + str(caregiver_id), "content", 101)
    )

    alerts = scan_alerts(
        None,
        now=datetime(2026, 10, 13, 11, 0, tzinfo=UTC),
        grace=timedelta(minutes=120),
        overlap=timedelta(minutes=30),
        cursor=FakeScanCursor(),
        schedules=FakeSchedules([occ]),
        dose_logs=FakeDoseLogs({(1, scheduled_at): 999}),
        access=FakeAccessGuard({patient_id: [caregiver_id]}),
        tokens=FakeTokens({caregiver_id: ["token_android_123"]}),
        notifications=notifications,
        checkpoints=SyncedCheckpoints(),
        pending=FakePending(),
        patient_names=FakePatientNames(),
    )

    # Không tạo thêm bản ghi mới và không gửi alert lặp
    assert len(notifications.created) == 1
    assert len(alerts) == 0


def test_dispatch_respects_revoked_consent_and_sharing_switch():
    # AC4: Thu hồi quyền/consent -> caregivers_of rỗng -> không notification/Alert.
    patient_id = uuid4()
    scheduled_at = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)

    occ = SimpleNamespace(patient_id=patient_id, schedule_id=1, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    alerts = scan_alerts(
        None,
        now=datetime(2026, 10, 13, 11, 0, tzinfo=UTC),
        grace=timedelta(minutes=120),
        overlap=timedelta(minutes=30),
        cursor=FakeScanCursor(),
        schedules=FakeSchedules([occ]),
        dose_logs=FakeDoseLogs({(1, scheduled_at): 999}),
        access=FakeAccessGuard({patient_id: []}),  # không có caregiver nào đủ quyền
        tokens=FakeTokens({uuid4(): ["token_android_123"]}),
        notifications=notifications,
        checkpoints=SyncedCheckpoints(),
        pending=FakePending(),
        patient_names=FakePatientNames(),
    )

    assert len(notifications.created) == 0
    assert len(alerts) == 0


def test_alert_payload_hides_medication_details_and_patient_name():
    # AC5: Push không có thuốc/liều lượng/giờ (CD6, QD-26); 3.19 Q10: không có cả tên patient.
    alert = Alert(notification_id=105, recipient_id=uuid4(), device_token="fcm_token_xyz")

    payload = build_fcm_payload(alert)

    assert payload["message"]["token"] == "fcm_token_xyz"
    assert payload["message"]["notification"]["title"] == "DrugTime"
    assert payload["message"]["notification"]["body"] == "Bạn có cảnh báo mới về người thân"
    assert payload["message"]["data"]["notification_id"] == "105"

    # Không lộ thông tin y tế nhạy cảm
    body = payload["message"]["notification"]["body"].lower()
    for forbidden in ["paracetamol", "aspirin", "viên", "mg", "ml", "uống lúc"]:
        assert forbidden not in body


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        if isinstance(self.row, list):
            return self.row[0] if self.row else None
        return self.row

    def one(self):
        if isinstance(self.row, list):
            return self.row[0]
        return self.row

    def __iter__(self):
        if self.row is None:
            return iter([])
        if isinstance(self.row, list):
            return iter(self.row)
        return iter([self.row])


class FakeConnection:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return FakeResult(self.results.pop(0))


class FakeUow:
    def __init__(self, connection):
        self.connection = connection


def test_sql_notifications_create_missed_alert():
    from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlNotifications

    connection = FakeConnection([SimpleNamespace(id=101)])
    user_id = uuid4()
    patient_id = uuid4()

    nid = SqlNotifications().create_missed_alert(
        FakeUow(connection),
        user_id,
        patient_id,
        "bo_lo:1:u1",
        "Bác An chưa uống thuốc",
        medication_name="Test medication",
        scheduled_at=datetime(2026, 10, 13, 8, tzinfo=UTC),
    )

    assert nid == 101
    assert connection.calls[0][1]["k"] == "bo_lo:1:u1"
    assert connection.calls[0][1]["content"] == "Bác An chưa uống thuốc"


def test_sql_notifications_create_missed_alert_conflict_returns_none():
    from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlNotifications

    connection = FakeConnection([None])
    user_id = uuid4()
    patient_id = uuid4()

    nid = SqlNotifications().create_missed_alert(
        FakeUow(connection),
        user_id,
        patient_id,
        "bo_lo:1:u1",
        medication_name="Test medication",
        scheduled_at=datetime(2026, 10, 13, 8, tzinfo=UTC),
    )

    assert nid is None


def test_sql_notifications_list_for_user():
    from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlNotifications

    user_id = uuid4()
    patient_id = uuid4()
    created_at = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)

    item_row = SimpleNamespace(
        id=202,
        user_id=user_id,
        about_patient_user_id=patient_id,
        type="canh_bao_bo_lo_lieu_nguoi_than",
        content="Bác Bình chưa uống thuốc",
        is_read=False,
        created_at=created_at,
        about_patient_name="Bình",
        medication_name="Test medication",
        scheduled_at=created_at,
    )

    connection = FakeConnection([[item_row], [item_row]])
    repo = SqlNotifications()
    metadata = repo.metadata(FakeUow(connection), user_id)
    assert metadata == [(202, patient_id)]
    items = repo.authorized_records(FakeUow(connection), user_id, [202])
    assert len(items) == 1
    assert items[0].id == 202
    assert items[0].about_patient_name is None  # identity lookup runs after PEP in the service
    assert items[0].medication_name == "Test medication"
    assert connection.calls[1][1] == {"u": user_id, "ids": [202]}


def test_sql_notifications_mark_as_read():
    from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlNotifications

    user_id = uuid4()
    patient_id = uuid4()
    created_at = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)

    updated_row = SimpleNamespace(
        id=303,
        user_id=user_id,
        about_patient_user_id=patient_id,
        type="canh_bao_bo_lo_lieu_nguoi_than",
        content="Bác Cường chưa uống thuốc",
        is_read=True,
        created_at=created_at,
        medication_name=None,
        scheduled_at=None,
    )
    user_row = SimpleNamespace(full_name="Cường")

    connection = FakeConnection(
        [
            updated_row,
            user_row,
        ]
    )

    rec = SqlNotifications().mark_as_read(
        FakeUow(connection),
        303,
        user_id,
        is_read=True,
    )

    assert rec is not None
    assert rec.id == 303
    assert rec.is_read is True
    assert rec.about_patient_name is None  # no cross-module SQL name lookup


def test_sql_notifications_mark_as_read_not_found():
    from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlNotifications

    user_id = uuid4()
    connection = FakeConnection([None])

    rec = SqlNotifications().mark_as_read(
        FakeUow(connection),
        999,
        user_id,
        is_read=True,
    )

    assert rec is None


@pytest.mark.parametrize("name", [None, "", "   ", 42])
def test_missing_snapshot_fails_before_notification_insert(name):
    from unittest.mock import Mock

    patient, recipient = uuid4(), uuid4()
    at = datetime(2026, 10, 22, 8, tzinfo=UTC)
    schedules = FakeSchedules([SimpleNamespace(schedule_id=1, patient_id=patient, scheduled_at=at)])
    schedules.alert_context = lambda *a: name
    notifications = Mock()
    with pytest.raises(ValueError, match="snapshot unavailable"):
        scan_alerts(
            None,
            now=at + timedelta(hours=3),
            grace=timedelta(minutes=120),
            overlap=timedelta(minutes=30),
            cursor=FakeScanCursor(),
            schedules=schedules,
            dose_logs=FakeDoseLogs({(1, at): 99}),
            access=FakeAccessGuard({patient: [recipient]}),
            tokens=FakeTokens(),
            notifications=notifications,
            checkpoints=SyncedCheckpoints(),
            pending=FakePending(),
            patient_names=FakePatientNames(),
        )
    notifications.create_missed_alert.assert_not_called()
