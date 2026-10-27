from datetime import UTC, datetime
from uuid import uuid4

from drugtime.modules.adherence.application.confirm_doses import confirm_doses
from drugtime.modules.adherence.domain.dose import (
    ClientUuidConflict,
    DoseConfirmation,
    DoseConfirmationPersistenceResult,
    DoseLogRecord,
    DoseStatus,
)
from drugtime.shared.errors import Forbidden

NOW = datetime(2026, 10, 2, 2, 0, tzinfo=UTC)


class FakeUow:
    connection = None


class FakeAccess:
    def __init__(self, forbidden_patients=None):
        self.calls = []
        self.forbidden_patients = set(forbidden_patients or [])

    def authorize_dose_write(self, uow, caller_id, caller_is_admin, patient_id):
        self.calls.append((caller_id, caller_is_admin, patient_id))
        if patient_id in self.forbidden_patients:
            raise Forbidden("forbidden")

    def caregivers_of(self, uow, patient_id):
        return []


class FakeSchedules:
    def __init__(self, owners):
        self.owners = owners

    def owner(self, uow, schedule_id):
        return self.owners.get(schedule_id)

    def ids_of(self, uow, user_id):
        return []

    def occurrences_between(self, uow, start, end):
        return []


class FakeDoseLogs:
    def __init__(self, *, conflict=False):
        self.conflict = conflict
        self.calls = []

    def upsert_confirmation(self, uow, c, status):
        self.calls.append((c, status))
        if self.conflict:
            raise ClientUuidConflict()
        record = DoseLogRecord(
            id=9001,
            client_uuid=c.client_uuid,
            schedule_id=c.schedule_id,
            scheduled_at=c.scheduled_at,
            taken_at=c.taken_at,
            status=status,
            synced_at=NOW,
        )
        return DoseConfirmationPersistenceResult(
            record=record,
            adherence_counted=status is not DoseStatus.MISSED,
        )

    def mark_missed(self, uow, schedule_id, scheduled_at):
        return None

    def erase_for_schedules(self, uow, schedule_ids):
        pass


def _confirmation(schedule_id=1, scheduled_at=None, taken_at=None):
    scheduled_at = scheduled_at or datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = taken_at or datetime(2026, 10, 2, 1, 5, 59, 999999, tzinfo=UTC)
    return DoseConfirmation(uuid4(), schedule_id, scheduled_at, taken_at)


def test_confirm_doses_returns_partial_success_without_raising_for_item_errors():
    # AC7: Một item lỗi nghiệp vụ không làm rollback/chặn item hợp lệ trong cùng batch.
    caller_id = uuid4()
    dose_logs = FakeDoseLogs()

    result = confirm_doses(
        FakeUow(),
        caller_id=caller_id,
        caller_is_admin=False,
        items=[
            _confirmation(1),
            _confirmation(
                2,
                scheduled_at=datetime(2026, 10, 2, 1, 0, tzinfo=UTC),
                taken_at=datetime(2026, 10, 2, 0, 29, 59, 999999, tzinfo=UTC),
            ),
        ],
        now=datetime(2026, 10, 2, 18, 0, tzinfo=UTC),
        access=FakeAccess(),
        schedules=FakeSchedules({1: caller_id, 2: caller_id}),
        dose_logs=dose_logs,
    )

    assert result.synced == 1
    assert result.failed == 1
    assert result.items[0].result == "synced"
    assert result.items[0].dose_status is DoseStatus.TAKEN
    assert result.items[0].scheduled_at == datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    assert result.items[0].adherence_counted is True
    assert result.items[1].error is not None
    assert result.items[1].error.code == "taken_at_too_early"
    assert len(dose_logs.calls) == 1


def test_confirm_doses_uses_schedule_owner_for_access_guard_before_write():
    # AC8: Use case phải lấy owner của schedule rồi gọi PEP trước khi ghi dose_logs.
    caller_id = uuid4()
    owner_id = uuid4()
    access = FakeAccess()
    dose_logs = FakeDoseLogs()

    result = confirm_doses(
        FakeUow(),
        caller_id=caller_id,
        caller_is_admin=False,
        items=[_confirmation(1)],
        now=NOW,
        access=access,
        schedules=FakeSchedules({1: owner_id}),
        dose_logs=dose_logs,
    )

    assert result.synced == 1
    assert access.calls == [(caller_id, False, owner_id)]
    assert len(dose_logs.calls) == 1


def test_confirm_doses_maps_forbidden_schedule_to_item_403():
    # AC8: Lịch thuộc patient không có quyền phải thành item failed 403 và không ghi DB.
    caller_id = uuid4()
    owner_id = uuid4()
    dose_logs = FakeDoseLogs()

    result = confirm_doses(
        FakeUow(),
        caller_id=caller_id,
        caller_is_admin=False,
        items=[_confirmation(1)],
        now=NOW,
        access=FakeAccess(forbidden_patients={owner_id}),
        schedules=FakeSchedules({1: owner_id}),
        dose_logs=dose_logs,
    )

    assert result.failed == 1
    assert result.items[0].error is not None
    assert result.items[0].error.code == "forbidden_schedule"
    assert result.items[0].error.http_status == 403
    assert not dose_logs.calls


def test_confirm_doses_maps_missing_schedule_to_item_404():
    # AC16: schedule_id không tồn tại là lỗi từng item 404, không phải lỗi toàn batch.
    caller_id = uuid4()
    dose_logs = FakeDoseLogs()

    result = confirm_doses(
        FakeUow(),
        caller_id=caller_id,
        caller_is_admin=False,
        items=[_confirmation(404)],
        now=NOW,
        access=FakeAccess(),
        schedules=FakeSchedules({}),
        dose_logs=dose_logs,
    )

    assert result.failed == 1
    assert result.items[0].error is not None
    assert result.items[0].error.code == "schedule_not_found"
    assert result.items[0].error.http_status == 404
    assert not dose_logs.calls


def test_confirm_doses_maps_client_uuid_conflict_to_item_409():
    # AC2: client_uuid đã dùng cho payload khác phải trả item conflict 409.
    caller_id = uuid4()

    result = confirm_doses(
        FakeUow(),
        caller_id=caller_id,
        caller_is_admin=False,
        items=[_confirmation(1)],
        now=NOW,
        access=FakeAccess(),
        schedules=FakeSchedules({1: caller_id}),
        dose_logs=FakeDoseLogs(conflict=True),
    )

    assert result.failed == 1
    assert result.items[0].error is not None
    assert result.items[0].error.code == "client_uuid_conflict"
    assert result.items[0].error.http_status == 409


def test_confirm_doses_preserves_timestamp_precision_before_upsert_and_status_classification():
    # AC18: Use case giữ nguyên seconds/subseconds trước cả phân loại status và upsert.
    caller_id = uuid4()
    dose_logs = FakeDoseLogs()
    item = _confirmation(
        1,
        scheduled_at=datetime(2026, 10, 2, 1, 0, 59, 999999, tzinfo=UTC),
        taken_at=datetime(2026, 10, 2, 1, 30, 59, 999999, tzinfo=UTC),
    )

    result = confirm_doses(
        FakeUow(),
        caller_id=caller_id,
        caller_is_admin=False,
        items=[item],
        now=datetime(2026, 10, 2, 1, 31, tzinfo=UTC),
        access=FakeAccess(),
        schedules=FakeSchedules({1: caller_id}),
        dose_logs=dose_logs,
    )

    saved, status = dose_logs.calls[0]
    assert saved.scheduled_at == datetime(2026, 10, 2, 1, 0, 59, 999999, tzinfo=UTC)
    assert saved.taken_at == datetime(2026, 10, 2, 1, 30, 59, 999999, tzinfo=UTC)
    assert status is DoseStatus.TAKEN
    assert result.items[0].scheduled_at == saved.scheduled_at


def test_confirm_doses_syncs_after_plus_120_minutes_as_missed():
    # AC20/AC21: Sau +120 phút upload vẫn synced, nhưng adherence giữ bo_lo.
    caller_id = uuid4()
    dose_logs = FakeDoseLogs()
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    item = _confirmation(
        1,
        scheduled_at=scheduled_at,
        taken_at=scheduled_at.replace(hour=3, minute=0, microsecond=1),
    )

    result = confirm_doses(
        FakeUow(),
        caller_id=caller_id,
        caller_is_admin=False,
        items=[item],
        now=datetime(2026, 10, 2, 3, 1, tzinfo=UTC),
        access=FakeAccess(),
        schedules=FakeSchedules({1: caller_id}),
        dose_logs=dose_logs,
    )

    assert result.synced == 1
    assert result.items[0].dose_status is DoseStatus.MISSED
    assert result.items[0].adherence_counted is False
    assert len(dose_logs.calls) == 1
