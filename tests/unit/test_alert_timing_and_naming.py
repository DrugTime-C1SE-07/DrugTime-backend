import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from drugtime.modules.adherence.application.scan_missed_doses import scan, scan_and_notify
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


class FakeNotifier:
    def __init__(self):
        self.sent_alerts = []
        self.payloads = []

    def send(self, alerts: list[Alert]) -> None:
        self.sent_alerts.extend(alerts)
        for alert in alerts:
            self.payloads.append(build_fcm_payload(alert))


@contextmanager
def dummy_uow():
    yield None


def test_alert_timing_under_2_seconds_batch_sizes():
    """AC1: Toàn trình quét và phát sinh thông báo đạt SLO p95 < 2s (QD-25, NFR05) cho các kích thước mẻ (1, 10, 50 liều)."""
    batch_sizes = [1, 10, 50]
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    scheduled_at = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)

    timing_results = {}

    for size in batch_sizes:
        occurrences = []
        missed_map = {}
        caregivers_map = {}
        tokens_map = {}
        names_map = {}

        for i in range(size):
            p_id = uuid4()
            c_id = uuid4()
            sch_id = i + 1
            occurrences.append(SimpleNamespace(patient_id=p_id, schedule_id=sch_id, scheduled_at=scheduled_at))
            missed_map[(sch_id, scheduled_at)] = 1000 + i
            caregivers_map[p_id] = [c_id]
            tokens_map[c_id] = [f"token_android_{i}"]
            names_map[p_id] = f"Bệnh nhân {i}"

        notifications = FakeNotifications()
        cursor = FakeScanCursor(initial=datetime(2026, 10, 14, 8, 0, tzinfo=UTC))
        notifier = FakeNotifier()

        # Đo lường thời gian toàn trình thực thi scan_and_notify
        start_time = time.perf_counter()

        alert_count = scan_and_notify(
            uow_factory=dummy_uow,
            notifier=notifier,
            now=now,
            grace=timedelta(minutes=120),
            overlap=timedelta(minutes=30),
            cursor=cursor,
            schedules=FakeSchedules(occurrences),
            dose_logs=FakeDoseLogs(missed_map),
            access=FakeAccessGuard(caregivers_map),
            tokens=FakeTokens(tokens_map),
            notifications=notifications,
            patient_names=FakePatientNames(names_map),
        )

        elapsed = time.perf_counter() - start_time
        timing_results[size] = elapsed

        # Khẳng định số lượng cảnh báo khớp kích thước mẻ
        assert alert_count == size
        assert len(notifier.sent_alerts) == size
        assert len(notifications.created) == size

        # Khẳng định thời gian thực thi strictly < 2.0s
        assert elapsed < 2.0, f"Batch size {size} took {elapsed:.4f}s, exceeding 2.0s SLO threshold"

    # Log kết quả benchmark
    print(f"\n[BENCHMARK] Timing results: 1 item = {timing_results[1]:.5f}s, 10 items = {timing_results[10]:.5f}s, 50 items = {timing_results[50]:.5f}s")


def test_alert_explicitly_names_patient_vietnamese():
    """AC2: Alert phải nêu đích danh tên bệnh nhân theo mẫu 'Bác [Tên] chưa ghi nhận liều thuốc đúng giờ' (PB20)."""
    vietnamese_names = [
        "Nguyễn Văn An",
        "Trần Thị Mai",
        "Phan Lê Quỳnh Như",
        "Đỗ Đức Dũng",
        "Hoàng Thị Bích Ngọc",
    ]

    for name in vietnamese_names:
        patient_id = uuid4()
        caregiver_id = uuid4()
        scheduled_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
        occ = SimpleNamespace(patient_id=patient_id, schedule_id=101, scheduled_at=scheduled_at)
        notifications = FakeNotifications()

        alerts = scan(
            None,
            now=datetime(2026, 10, 14, 11, 0, tzinfo=UTC),
            grace=timedelta(minutes=120),
            overlap=timedelta(minutes=30),
            cursor=FakeScanCursor(),
            schedules=FakeSchedules([occ]),
            dose_logs=FakeDoseLogs({(101, scheduled_at): 888}),
            access=FakeAccessGuard({patient_id: [caregiver_id]}),
            tokens=FakeTokens({caregiver_id: ["token_fcm_android"]}),
            notifications=notifications,
            patient_names=FakePatientNames({patient_id: name}),
        )

        assert len(alerts) == 1
        alert = alerts[0]

        # Kiểm tra tiêu đề app và nội dung có đúng tên bệnh nhân
        assert alert.title == "DrugTime"
        expected_content = f"Bác {name} chưa ghi nhận liều thuốc đúng giờ"
        assert alert.body == expected_content
        assert notifications.created[0][3] == expected_content

        # Kiểm tra payload FCM
        payload = build_fcm_payload(alert)
        assert payload["message"]["notification"]["title"] == "DrugTime"
        assert payload["message"]["notification"]["body"] == expected_content
        assert payload["message"]["data"]["notification_id"] == str(alert.notification_id)


def test_alert_fallback_when_patient_name_empty_or_none():
    """AC3: Khi tên bệnh nhân là None hoặc rỗng, fallback về nội dung chung an toàn, không ném exception hay hiện 'Bác None'."""
    test_cases = [None, ""]

    for name in test_cases:
        patient_id = uuid4()
        caregiver_id = uuid4()
        scheduled_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
        occ = SimpleNamespace(patient_id=patient_id, schedule_id=102, scheduled_at=scheduled_at)
        notifications = FakeNotifications()

        alerts = scan(
            None,
            now=datetime(2026, 10, 14, 11, 0, tzinfo=UTC),
            grace=timedelta(minutes=120),
            overlap=timedelta(minutes=30),
            cursor=FakeScanCursor(),
            schedules=FakeSchedules([occ]),
            dose_logs=FakeDoseLogs({(102, scheduled_at): 889}),
            access=FakeAccessGuard({patient_id: [caregiver_id]}),
            tokens=FakeTokens({caregiver_id: ["token_android"]}),
            notifications=notifications,
            patient_names=FakePatientNames({patient_id: name}),
        )

        assert len(alerts) == 1
        alert = alerts[0]

        # Tuyệt đối không hiển thị "Bác None" hoặc "Bác "
        assert "Bác None" not in alert.body
        assert "Bác " not in alert.body

        # Fallback nội dung an toàn theo quy định
        assert alert.body == "Bạn có cảnh báo mới về người thân"
        assert notifications.created[0][3] == "Chưa ghi nhận liều thuốc đúng giờ"


def test_alert_payload_negative_check_health_privacy_cd6():
    """AC4: Quét phủ định kiểm soát rò rỉ dữ liệu y tế (CD6, QD-26): không chứa tên thuốc, hàm lượng, dạng dùng hay giờ uống cụ thể."""
    patient_id = uuid4()
    caregiver_id = uuid4()
    scheduled_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    occ = SimpleNamespace(patient_id=patient_id, schedule_id=103, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    alerts = scan(
        None,
        now=datetime(2026, 10, 14, 11, 0, tzinfo=UTC),
        grace=timedelta(minutes=120),
        overlap=timedelta(minutes=30),
        cursor=FakeScanCursor(),
        schedules=FakeSchedules([occ]),
        dose_logs=FakeDoseLogs({(103, scheduled_at): 890}),
        access=FakeAccessGuard({patient_id: [caregiver_id]}),
        tokens=FakeTokens({caregiver_id: ["token_android"]}),
        notifications=notifications,
        patient_names=FakePatientNames({patient_id: "Lê Văn C"}),
    )

    alert = alerts[0]
    payload = build_fcm_payload(alert)

    # Tập các từ khóa y tế nhạy cảm tuyệt đối cấm xuất hiện trong push
    forbidden_terms = [
        "paracetamol", "panadol", "metformin", "amlodipine", "aspirin", "insulin",
        "viên", "gói", "mg", "ml", "mcg", "ui", "liều lượng", "uống lúc", "8:00", "08:00",
        "phác đồ", "toa thuốc", "đơn thuốc", "bệnh án", "chẩn đoán"
    ]

    all_text = (
        f"{alert.title} {alert.body} "
        f"{notifications.created[0][3]} "
        f"{payload['message']['notification']['title']} {payload['message']['notification']['body']} "
        f"{str(payload['message']['data'])}"
    ).lower()

    for term in forbidden_terms:
        assert term not in all_text, f"Forbidden medical term '{term}' found in alert content!"


def test_alert_platform_routing_android_push_ios_db_only():
    """AC5, AC6: Phân luồng chính xác theo nền tảng: Android nhận push FCM, iOS không push APNs nhưng nhận thông báo DB (C-06, C-07, BS-03)."""
    patient_id = uuid4()
    android_user = uuid4()
    ios_user = uuid4()
    mixed_user = uuid4()

    scheduled_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    occ = SimpleNamespace(patient_id=patient_id, schedule_id=104, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    # android_tokens() adapter chỉ trả về token Android cho android_user và mixed_user
    # ios_user không có token Android
    android_tokens_map = {
        android_user: ["fcm_token_android_only"],
        ios_user: [],  # iOS không có Android FCM token
        mixed_user: ["fcm_token_android_device"],
    }

    alerts = scan(
        None,
        now=datetime(2026, 10, 14, 11, 0, tzinfo=UTC),
        grace=timedelta(minutes=120),
        overlap=timedelta(minutes=30),
        cursor=FakeScanCursor(),
        schedules=FakeSchedules([occ]),
        dose_logs=FakeDoseLogs({(104, scheduled_at): 891}),
        access=FakeAccessGuard({patient_id: [android_user, ios_user, mixed_user]}),
        tokens=FakeTokens(android_tokens_map),
        notifications=notifications,
        patient_names=FakePatientNames({patient_id: "Nguyễn Văn D"}),
    )

    # 1. Cả 3 người thân đều có bản ghi notifications trong CSDL để xem khi mở app
    created_recipients = {item[0] for item in notifications.created}
    assert android_user in created_recipients
    assert ios_user in created_recipients
    assert mixed_user in created_recipients
    assert len(notifications.created) == 3

    # 2. Nhưng Alert push chỉ phát sinh cho Android token (tổng cộng 2 push)
    alert_recipients = {alert.recipient_id for alert in alerts}
    assert android_user in alert_recipients
    assert mixed_user in alert_recipients
    assert ios_user not in alert_recipients
    assert len(alerts) == 2


def test_alert_no_false_alerts_if_dose_already_confirmed():
    """AC7: Chống cảnh báo sai (false alert): nếu bệnh nhân đã xác nhận liều trước khi quét, không gửi cảnh báo cho người thân."""
    patient_id = uuid4()
    caregiver_id = uuid4()
    scheduled_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    occ = SimpleNamespace(patient_id=patient_id, schedule_id=105, scheduled_at=scheduled_at)
    notifications = FakeNotifications()

    # mark_missed trả về None vì liều này đã được xác nhận (hoặc đã được đánh dấu ở lượt trước)
    dose_logs = FakeDoseLogs({(105, scheduled_at): None})
    cursor = FakeScanCursor(initial=datetime(2026, 10, 14, 7, 0, tzinfo=UTC))

    alerts = scan(
        None,
        now=datetime(2026, 10, 14, 11, 0, tzinfo=UTC),
        grace=timedelta(minutes=120),
        overlap=timedelta(minutes=30),
        cursor=cursor,
        schedules=FakeSchedules([occ]),
        dose_logs=dose_logs,
        access=FakeAccessGuard({patient_id: [caregiver_id]}),
        tokens=FakeTokens({caregiver_id: ["token_android"]}),
        notifications=notifications,
        patient_names=FakePatientNames({patient_id: "Nguyễn Văn E"}),
    )

    # Không có thông báo hay cảnh báo nào được tạo
    assert len(notifications.created) == 0
    assert len(alerts) == 0

    # Cursor vẫn được tiến lên an toàn
    assert cursor.advanced_to == datetime(2026, 10, 14, 11, 0, tzinfo=UTC) - timedelta(minutes=120)
