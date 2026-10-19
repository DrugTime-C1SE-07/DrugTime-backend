"""Khóa tài khoản nhập sai mã liên kết (task 3.13, QD-34 (c))."""

from datetime import UTC, datetime, timedelta

from drugtime.modules.family.domain.link_request import LinkRequestLimits
from drugtime.modules.family.domain.throttle import (
    ThrottleState,
    is_locked,
    on_failure,
    retry_after,
)

NOW = datetime(2026, 10, 16, 2, 30, tzinfo=UTC)
LIMITS = LinkRequestLimits()


def test_fifth_failure_locks_account__AC10():
    assert on_failure(ThrottleState(failures_in_window=4), NOW, LIMITS) is not None


def test_fourth_failure_does_not_lock():
    assert on_failure(ThrottleState(failures_in_window=3), NOW, LIMITS) is None
    assert on_failure(ThrottleState(), NOW, LIMITS) is None


def test_locked_until_is_15_min_after_fifth__AC10():
    until = on_failure(ThrottleState(failures_in_window=4), NOW, LIMITS)

    assert until == NOW + timedelta(minutes=15)
    assert is_locked(ThrottleState(locked_until=until), NOW + timedelta(minutes=14, seconds=59))
    assert not is_locked(ThrottleState(locked_until=until), until)


def test_old_failures_outside_window_not_counted__AC11():
    # 4 lần sai nhưng lần đầu đã ra khỏi cửa sổ: adapter chỉ đếm được 3, lần sai mới là thứ 4.
    assert on_failure(ThrottleState(failures_in_window=3), NOW, LIMITS) is None


def test_thresholds_come_from_limits():
    limits = LinkRequestLimits(fail_account_limit=3, lock_duration=timedelta(minutes=5))

    assert on_failure(ThrottleState(failures_in_window=2), NOW, limits) == NOW + timedelta(
        minutes=5
    )


def test_not_locked_without_lock():
    assert not is_locked(ThrottleState(failures_in_window=4), NOW)


def test_retry_after_rounds_up_min_1():
    assert retry_after(NOW + timedelta(seconds=540), NOW) == 540
    assert retry_after(NOW + timedelta(seconds=59, milliseconds=1), NOW) == 60
    assert retry_after(NOW + timedelta(milliseconds=10), NOW) == 1
    assert retry_after(NOW, NOW) == 1
