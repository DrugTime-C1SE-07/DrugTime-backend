from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from drugtime.modules.adherence.application.scan_missed_doses import scan
from drugtime.modules.adherence.domain.alert import Alert
from drugtime.notification_gateway.fcm import build_fcm_payload


class FakeSchedules:
    def __init__(self, occurrences):
        self.occurrences = occurrences

    def occurrences_between(self, uow, start, until):
        return self.occurrences


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

    def create_missed_alert(self, uow, recipient_id, patient_id, dedupe_key, content=None):
        for r_id, p_id, k, c, nid in self.created:
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


def test_dispatch_creates_alert_for_android_caregiver():
    # AC1: Bệnh nhân bỏ lỡ liều, người thân có liên kết & token Android -> tạo notification & gửi push Alert
    patient_id = uuid4()
    caregiver_id = uuid4()
    scheduled_at = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)

    occ = SimpleNamespace(patient_id=patient_id, schedule_id=1, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    alerts = scan(
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
        patient_names=FakePatientNames({patient_id: "Nguyễn Văn A"}),
    )

    assert len(notifications.created) == 1
    assert notifications.created[0][0] == caregiver_id
    assert "Nguyễn Văn A" in notifications.created[0][3]

    assert len(alerts) == 1
    assert alerts[0].recipient_id == caregiver_id
    assert alerts[0].device_token == "token_android_123"
    assert "Nguyễn Văn A" in alerts[0].body


def test_dispatch_skips_push_for_ios_caregiver_but_creates_notification_row():
    # AC2: Người thân chỉ dùng iOS (không có token trong android_tokens) -> có dòng notifications, KHÔNG có Alert push
    patient_id = uuid4()
    caregiver_id = uuid4()
    scheduled_at = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)

    occ = SimpleNamespace(patient_id=patient_id, schedule_id=1, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    alerts = scan(
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
    notifications.created.append((caregiver_id, patient_id, "bo_lo:999:" + str(caregiver_id), "content", 101))

    alerts = scan(
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
        patient_names=FakePatientNames(),
    )

    # Không tạo thêm bản ghi mới và không gửi alert lặp
    assert len(notifications.created) == 1
    assert len(alerts) == 0


def test_dispatch_respects_revoked_consent_and_sharing_switch():
    # AC4: Người thân đã bị thu hồi quyền hoặc rút consent -> access.caregivers_of trả rỗng -> không tạo notification hay alert
    patient_id = uuid4()
    scheduled_at = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)

    occ = SimpleNamespace(patient_id=patient_id, schedule_id=1, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    alerts = scan(
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
        patient_names=FakePatientNames(),
    )

    assert len(notifications.created) == 0
    assert len(alerts) == 0


def test_alert_payload_hides_medication_details_and_names_patient():
    # AC5: Nội dung push tuyệt đối không có tên thuốc, liều lượng, giờ uống cụ thể (CD6, QD-26), chỉ nêu tên bệnh nhân
    alert = Alert(
        notification_id=105,
        recipient_id=uuid4(),
        device_token="fcm_token_xyz",
        title="DrugTime",
        body="Bác Nguyễn Văn A chưa ghi nhận liều thuốc đúng giờ",
    )

    payload = build_fcm_payload(alert)

    assert payload["message"]["token"] == "fcm_token_xyz"
    assert payload["message"]["notification"]["title"] == "DrugTime"
    assert payload["message"]["notification"]["body"] == "Bác Nguyễn Văn A chưa ghi nhận liều thuốc đúng giờ"
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
    )

    connection = FakeConnection([
        SimpleNamespace(total=1),
        SimpleNamespace(unread=1),
        [item_row],
    ])

    items, total, unread = SqlNotifications().list_for_user(
        FakeUow(connection),
        user_id,
        is_read=None,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert unread == 1
    assert len(items) == 1
    assert items[0].id == 202
    assert items[0].about_patient_name == "Bình"


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
    )
    user_row = SimpleNamespace(full_name="Cường")

    connection = FakeConnection([
        updated_row,
        user_row,
    ])

    rec = SqlNotifications().mark_as_read(
        FakeUow(connection),
        303,
        user_id,
        is_read=True,
    )

    assert rec is not None
    assert rec.id == 303
    assert rec.is_read is True
    assert rec.about_patient_name == "Cường"


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
