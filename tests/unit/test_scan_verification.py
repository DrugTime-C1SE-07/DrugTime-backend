"""Task 3.19 (P9, P10): lượt quét có xác minh, hàng chờ xác minh, gõ cửa, dọn token với port giả."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from drugtime.modules.adherence.application.scan_missed_doses import (
    ScanResult,
    scan,
    scan_and_notify,
)
from drugtime.modules.adherence.domain.alert import SyncRequest

L = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)  # 08:00 VN Thứ Hai 05/10/2026
D = L + timedelta(minutes=120)
PATIENT, FAMILY = uuid4(), uuid4()
GENERIC = "Bạn có cảnh báo mới về người thân"


def occ(at=L, schedule_id=1, patient=PATIENT):
    return SimpleNamespace(schedule_id=schedule_id, patient_id=patient, scheduled_at=at)


class Schedules:
    def __init__(self, occurrences):
        self.occurrences = list(occurrences)

    def occurrences_between(self, uow, start, end):
        return [o for o in self.occurrences if start <= o.scheduled_at < end]

    def alert_context(self, uow, schedule_id, patient_id):
        return "Test medication"


class DoseLogs:
    """Dòng dose_logs giả: mark_missed chỉ tạo khi chưa có (ON CONFLICT DO NOTHING)."""

    def __init__(self, confirmed=()):
        self.rows = {k: "da_uong" for k in confirmed}
        self.next_id = 0

    def mark_missed(self, uow, schedule_id, scheduled_at):
        if (schedule_id, scheduled_at) in self.rows:
            return None
        self.rows[(schedule_id, scheduled_at)] = "bo_lo"
        self.next_id += 1
        return self.next_id


class Pending:
    """Hàng chờ giả có cùng hợp đồng với SqlPendingVerifications."""

    def __init__(self, dose_logs, checkpoints):
        self.dose_logs, self.checkpoints = dose_logs, checkpoints
        self.rows = {}

    def add(self, uow, o):
        key = (o.schedule_id, o.scheduled_at)
        if key in self.dose_logs.rows or key in self.rows:
            return False
        self.rows[key] = o
        return True

    def verified(self, uow, now):
        return [
            o
            for o in sorted(self.rows.values(), key=lambda o: (o.scheduled_at, o.schedule_id))
            if (cp := self.checkpoints.values.get(o.patient_id)) is not None
            and cp >= o.scheduled_at + timedelta(minutes=120)
            and now > o.scheduled_at + timedelta(minutes=120)
        ]

    def remove(self, uow, o):
        self.rows.pop((o.schedule_id, o.scheduled_at), None)

    def purge_recorded(self, uow):
        for key in [k for k in self.rows if k in self.dose_logs.rows]:
            del self.rows[key]


class Checkpoints:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_many(self, uow, user_ids):
        return {u: self.values[u] for u in user_ids if u in self.values}


class Tokens:
    def __init__(self, android):
        self.android = android
        self.removed = []

    def android_tokens(self, uow, user_ids):
        return [(u, t) for u in user_ids for t in self.android.get(u, [])]

    def remove(self, uow, tokens):
        self.removed.append(tokens)


class Notifications:
    def __init__(self):
        self.created = {}

    def create_missed_alert(self, uow, recipient_id, patient_id, key, content=None, **snapshot):
        if key in self.created:
            return None
        self.created[key] = dict(recipient=recipient_id, content=content, **snapshot)
        return len(self.created)


class World:
    def __init__(self, occurrences, *, checkpoint=None, confirmed=(), android=None, cursor=None):
        self.cursor_value = cursor
        self.dose_logs = DoseLogs(confirmed)
        self.checkpoints = Checkpoints({PATIENT: checkpoint} if checkpoint else {})
        self.pending = Pending(self.dose_logs, self.checkpoints)
        self.tokens = Tokens(
            android if android is not None else {FAMILY: ["family-token"], PATIENT: ["p-a1"]}
        )
        self.notifications = Notifications()
        self.schedules = Schedules(occurrences)

    def ports(self, now):
        world = self

        class Cursor:
            def get(self, uow):
                return world.cursor_value

            def advance(self, uow, until):
                world.cursor_value = until

        return dict(
            now=now,
            grace=timedelta(minutes=120),
            overlap=timedelta(minutes=30),
            cursor=Cursor(),
            schedules=self.schedules,
            dose_logs=self.dose_logs,
            access=SimpleNamespace(caregivers_of=lambda uow, p: [FAMILY]),
            tokens=self.tokens,
            notifications=self.notifications,
            checkpoints=self.checkpoints,
            pending=self.pending,
            patient_names=SimpleNamespace(get_patient_name=lambda uow, p: "Lan"),
        )

    def scan(self, now) -> ScanResult:
        return scan(None, **self.ports(now))


def test_verified_when_checkpoint_at_or_after_deadline__AC17_AC21():
    for checkpoint in (D + timedelta(minutes=5), D):
        world = World([occ()], checkpoint=checkpoint, cursor=L - timedelta(minutes=15))
        result = world.scan(D + timedelta(minutes=6))

        assert world.dose_logs.rows == {(1, L): "bo_lo"}
        [note] = world.notifications.created.values()
        assert note["medication_name"] == "Test medication" and note["scheduled_at"] == L
        assert [a.device_token for a in result.alerts] == ["family-token"]
        assert result.sync_requests == []
        assert world.pending.rows == {}


def test_unverified_goes_to_pending_and_knocks_once__AC18_AC37():
    for checkpoint in (None, D - timedelta(microseconds=1)):
        world = World([occ()], checkpoint=checkpoint, cursor=L - timedelta(minutes=15))
        result = world.scan(D + timedelta(minutes=1))

        assert world.dose_logs.rows == {}
        assert world.notifications.created == {}
        assert result.alerts == []
        assert result.sync_requests == [SyncRequest(PATIENT, "p-a1")]
        assert list(world.pending.rows) == [(1, L)]

        # Lượt chồng lấn kế tiếp: liều đã trong hàng chờ, không gõ cửa lại.
        again = world.scan(D + timedelta(minutes=16))
        assert again.sync_requests == [] and again.alerts == []


def test_pending_verified_later_records_missed__AC19():
    world = World([occ()], cursor=L - timedelta(minutes=15))
    world.scan(D + timedelta(minutes=1))
    # Cursor đi xa khỏi L; 15:00 VN patient mới đồng bộ.
    world.scan(D + timedelta(hours=5))
    world.checkpoints.values[PATIENT] = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)

    result = world.scan(datetime(2026, 10, 5, 8, 7, tzinfo=UTC))

    assert world.dose_logs.rows == {(1, L): "bo_lo"}
    assert [a.device_token for a in result.alerts] == ["family-token"]
    assert world.pending.rows == {}


def test_confirmed_while_pending_never_alerts__AC20():
    world = World([occ()], cursor=L - timedelta(minutes=15))
    world.scan(D + timedelta(minutes=1))
    world.dose_logs.rows[(1, L)] = "da_uong"  # xác nhận 08:10 tới cùng hàng chờ
    world.checkpoints.values[PATIENT] = D + timedelta(hours=5)

    result = world.scan(D + timedelta(hours=5, minutes=7))

    assert world.dose_logs.rows == {(1, L): "da_uong"}
    assert world.notifications.created == {} and result.alerts == []
    assert world.pending.rows == {}


def test_exact_deadline_not_processed__AC22():
    world = World([occ()], checkpoint=D + timedelta(hours=1), cursor=L - timedelta(minutes=15))

    assert world.scan(D) == ScanResult()
    assert world.dose_logs.rows == {} and world.pending.rows == {}

    result = world.scan(D + timedelta(seconds=1))
    assert world.dose_logs.rows == {(1, L): "bo_lo"} and len(result.alerts) == 1


def test_confirmed_dose_not_pending_not_knocked__AC23():
    world = World([occ()], confirmed=[(1, L)], cursor=L - timedelta(minutes=15))

    result = world.scan(D + timedelta(minutes=1))

    assert result == ScanResult()
    assert world.pending.rows == {} and world.notifications.created == {}


def test_one_knock_per_token_for_many_doses__AC37():
    doses = [occ(schedule_id=i) for i in (1, 2, 3)]
    world = World(doses, android={PATIENT: ["p-a1", "p-a2"]}, cursor=L - timedelta(minutes=15))

    result = world.scan(D + timedelta(minutes=1))

    assert sorted(r.device_token for r in result.sync_requests) == ["p-a1", "p-a2"]
    assert len(world.pending.rows) == 3


def test_alert_body_generic_without_patient_time_or_medication__AC36():
    # Offline ba ngày: mỗi liều một cảnh báo, mỗi push mang notification_id riêng, câu chung.
    doses = [occ(at=L + timedelta(days=d, hours=h)) for d in range(3) for h in (0, 4, 8)]
    world = World(doses, cursor=L - timedelta(minutes=15))
    for d in range(3):
        world.scan(L + timedelta(days=d, hours=11))
    world.checkpoints.values[PATIENT] = L + timedelta(days=3)

    result = world.scan(L + timedelta(days=3, minutes=7))

    assert len(result.alerts) == 9
    assert len({a.notification_id for a in result.alerts}) == 9
    assert {n["scheduled_at"] for n in world.notifications.created.values()} == {
        o.scheduled_at for o in doses
    }
    for alert in result.alerts:
        assert alert.body == GENERIC
        assert "Lan" not in alert.body and "Test medication" not in alert.body
    assert all("Lan" in n["content"] for n in world.notifications.created.values())


def test_unregistered_tokens_removed_after_commit__AC42():
    events = []
    world = World([occ()], cursor=L - timedelta(minutes=15))

    @contextmanager
    def transaction():
        events.append("begin")
        yield None
        events.append("commit")

    class Notifier:
        def send(self, alerts):
            events.append("send")
            return []

        def request_sync(self, requests):
            events.append("request_sync")
            return ["p-a1"]

    scan_and_notify(transaction, Notifier(), **world.ports(D + timedelta(minutes=1)))

    assert events == ["begin", "commit", "request_sync", "begin", "commit"]
    assert world.tokens.removed == [["p-a1"]]


def test_failed_alert_dispatch_does_not_block_sync_request():
    world = World([occ(), occ(at=L + timedelta(minutes=10), schedule_id=2)])
    world.checkpoints.values[PATIENT] = L + timedelta(minutes=125)  # chỉ L đã xác minh
    calls = []

    @contextmanager
    def transaction():
        yield None

    class Notifier:
        def send(self, alerts):
            raise RuntimeError("provider down")

        def request_sync(self, requests):
            calls.append(requests)
            return []

    assert scan_and_notify(transaction, Notifier(), **world.ports(D + timedelta(minutes=15))) == 1
    assert [r.device_token for r in calls[0]] == ["p-a1"]
