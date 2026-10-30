from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from drugtime.modules.adherence.domain.dose import (
    DoseConfirmation,
    DoseConfirmationError,
    DoseStatus,
    may_mark_missed,
    status_after_confirmation,
    status_for_confirmation,
    validate_confirmation,
)


@pytest.mark.parametrize(
    ("existing", "computed", "expected"),
    [
        # Chưa có dòng hoặc đang bo_lo: trạng thái tính từ taken_at (QD-03, 3.19 Q3).
        (None, DoseStatus.TAKEN, DoseStatus.TAKEN),
        (None, DoseStatus.LATE, DoseStatus.LATE),
        (None, DoseStatus.MISSED, DoseStatus.MISSED),
        (DoseStatus.MISSED, DoseStatus.TAKEN, DoseStatus.TAKEN),
        (DoseStatus.MISSED, DoseStatus.LATE, DoseStatus.LATE),
        (DoseStatus.MISSED, DoseStatus.MISSED, DoseStatus.MISSED),
        # Đã xác nhận: giữ nguyên (idempotent, không ghi đè).
        (DoseStatus.TAKEN, DoseStatus.LATE, DoseStatus.TAKEN),
        (DoseStatus.TAKEN, DoseStatus.MISSED, DoseStatus.TAKEN),
        (DoseStatus.LATE, DoseStatus.TAKEN, DoseStatus.LATE),
        (DoseStatus.LATE, DoseStatus.MISSED, DoseStatus.LATE),
    ],
)
def test_status_after_confirmation_matrix__AC27(existing, computed, expected):
    assert status_after_confirmation(existing, computed) is expected


def test_worker_never_overwrites():
    # Bất biến worker: job bỏ lỡ chỉ được tạo dòng mới, không ghi đè liều đã uống/trễ.
    assert may_mark_missed(None)
    assert not any(may_mark_missed(s) for s in DoseStatus)


def test_future_taken_at_rejected():
    # AC5: taken_at sau clock backend là dữ liệu không hợp lệ và phải bị reject.
    now = datetime.now(UTC)
    c = DoseConfirmation(uuid4(), 1, now, now + timedelta(minutes=5))
    with pytest.raises(DoseConfirmationError) as exc:
        validate_confirmation(c, now)
    assert exc.value.code == "taken_at_in_future"


def test_taken_at_at_minus_30_minutes_is_taken():
    # AC6: Đúng biên sớm 30 phút vẫn hợp lệ và tính là da_uong.
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = scheduled_at - timedelta(minutes=30)
    c = DoseConfirmation(uuid4(), 1, scheduled_at, taken_at)

    assert status_for_confirmation(c, scheduled_at + timedelta(hours=1)) is DoseStatus.TAKEN


def test_taken_at_at_plus_30_minutes_is_taken():
    # AC13: taken_at đúng ranh grace 30 phút vẫn là da_uong.
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = scheduled_at + timedelta(minutes=30)
    c = DoseConfirmation(uuid4(), 1, scheduled_at, taken_at)

    assert status_for_confirmation(c, taken_at) is DoseStatus.TAKEN


def test_taken_at_just_after_plus_30_minutes_is_late():
    # AC14/AC18: Chỉ cần quá +30 phút một microsecond là uong_tre.
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = scheduled_at + timedelta(minutes=30, microseconds=1)
    c = DoseConfirmation(uuid4(), 1, scheduled_at, taken_at)

    assert status_for_confirmation(c, taken_at) is DoseStatus.LATE


def test_taken_at_before_minus_30_minutes_is_too_early():
    # AC15/AC18: Trước biên -30 phút một microsecond bị reject, không tự làm tròn.
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = scheduled_at - timedelta(minutes=30, microseconds=1)
    c = DoseConfirmation(uuid4(), 1, scheduled_at, taken_at)

    with pytest.raises(DoseConfirmationError) as exc:
        validate_confirmation(c, taken_at)
    assert exc.value.code == "taken_at_too_early"


def test_taken_at_at_plus_120_minutes_is_late():
    # AC19: Đúng biên +120 phút vẫn là uong_tre.
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = scheduled_at + timedelta(minutes=120)
    c = DoseConfirmation(uuid4(), 1, scheduled_at, taken_at)

    assert status_for_confirmation(c, taken_at) is DoseStatus.LATE


def test_taken_at_after_plus_120_minutes_is_missed():
    # AC20/AC21: Sau +120 phút vẫn sync, nhưng adherence result giữ bo_lo.
    scheduled_at = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    taken_at = scheduled_at + timedelta(minutes=120, microseconds=1)
    c = DoseConfirmation(uuid4(), 1, scheduled_at, taken_at)

    assert status_for_confirmation(c, taken_at) is DoseStatus.MISSED


def test_confirmation_timestamps_preserve_seconds_and_subseconds():
    # AC18: Backend dùng timestamp gốc; không truncate nên 01:30:00.000001 đã là uong_tre.
    now = datetime(2026, 10, 2, 1, 30, 30, tzinfo=UTC)
    c = DoseConfirmation(
        uuid4(),
        1,
        datetime(2026, 10, 2, 1, 0, tzinfo=UTC),
        datetime(2026, 10, 2, 1, 30, 0, 1, tzinfo=UTC),
    )

    assert status_for_confirmation(c, now) is DoseStatus.LATE
