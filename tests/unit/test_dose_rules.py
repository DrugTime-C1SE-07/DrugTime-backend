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


def test_confirmation_transitions():
    # AC3/AC4: Xác nhận muộn chỉ chuyển dòng bo_lo sang uong_tre, không đổi dòng đã xác nhận.
    assert status_after_confirmation(None) is DoseStatus.TAKEN
    assert status_after_confirmation(DoseStatus.MISSED) is DoseStatus.LATE
    assert status_after_confirmation(DoseStatus.TAKEN) is DoseStatus.TAKEN
    assert status_after_confirmation(DoseStatus.LATE) is DoseStatus.LATE


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
