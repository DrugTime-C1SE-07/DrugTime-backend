"""Chặn gửi lại sau nhiều lần bị từ chối (BS-04) và ngày giờ Việt Nam (task 3.13)."""

from datetime import UTC, datetime, timedelta

from drugtime.modules.family.domain.link_request import (
    LinkRequestLimits,
    cooldown_until,
    next_vn_midnight,
    vn_day_start,
)

LIMITS = LinkRequestLimits()
T = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


def test_streak_1_to_4_not_blocked__AC8():
    for streak in range(0, 5):
        assert cooldown_until(streak, T, LIMITS) is None


def test_streak_5_blocked_until_24h__AC8b():
    until = cooldown_until(5, T, LIMITS)

    assert until == T + timedelta(hours=24)
    # T + 23:59 còn bị chặn, Retry-After = 60 giây; T + 24:00 hết chặn.
    assert (until - (T + timedelta(hours=23, minutes=59))).total_seconds() == 60
    assert not T + timedelta(hours=24) < until


def test_streak_5_after_24h_not_blocked__AC8b():
    until = cooldown_until(5, T, LIMITS)

    assert until is not None and T + timedelta(hours=25) >= until


def test_streak_6_not_blocked__AC8b():
    # Hết chặn rồi bị từ chối thêm 1 lần: bộ đếm đã về 0, gửi lại được ngay.
    for streak in (6, 7, 8, 9):
        assert cooldown_until(streak, T, LIMITS) is None


def test_streak_10_blocked__AC8b():
    assert cooldown_until(10, T, LIMITS) == T + timedelta(hours=24)


def test_no_rejection_time_not_blocked():
    assert cooldown_until(5, None, LIMITS) is None


def test_vn_day_start_and_next_midnight__AC14():
    # 16:59:59Z = 23:59:59 giờ VN ngày 16; 17:00:00Z = 00:00 giờ VN ngày 17.
    before = datetime(2026, 10, 16, 16, 59, 59, tzinfo=UTC)
    after = datetime(2026, 10, 16, 17, 0, 0, tzinfo=UTC)

    assert vn_day_start(before) == datetime(2026, 10, 15, 17, 0, tzinfo=UTC)
    assert next_vn_midnight(before) == after
    assert vn_day_start(after) == after
    assert next_vn_midnight(after) == datetime(2026, 10, 17, 17, 0, tzinfo=UTC)
    assert (next_vn_midnight(before) - before).total_seconds() == 1


def test_vn_day_start_is_aware():
    assert vn_day_start(T).utcoffset() == timedelta(hours=7)
