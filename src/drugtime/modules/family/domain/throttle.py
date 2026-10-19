"""Khóa tài khoản nhập sai mã liên kết nhiều lần (QD-34 (c), task 3.13)."""

import math
from dataclasses import dataclass
from datetime import datetime

from drugtime.modules.family.domain.link_request import LinkRequestLimits


@dataclass(frozen=True)
class ThrottleState:
    """Lượt sai của một tài khoản, đọc ở đầu request.

    failures_in_window: số lần sai trong cửa sổ trượt (chưa tính lượt đang xử lý).
    locked_until: thời điểm hết khóa muộn nhất đã ghi, hoặc None.
    client_uuid_failed: `client_uuid` của request đã được tính một lần sai trước đó.
    """

    failures_in_window: int = 0
    locked_until: datetime | None = None
    client_uuid_failed: bool = False


def is_locked(state: ThrottleState, now: datetime) -> bool:
    return state.locked_until is not None and now < state.locked_until


def on_failure(state: ThrottleState, now: datetime, limits: LinkRequestLimits) -> datetime | None:
    """Thời điểm hết khóa nếu lượt sai mới làm tài khoản đạt ngưỡng, ngược lại None.

    Khóa tính từ lần sai đạt ngưỡng, không tính từ lần sai đầu của cửa sổ.
    """
    if state.failures_in_window + 1 >= limits.fail_account_limit:
        return now + limits.lock_duration
    return None


def retry_after(until: datetime, now: datetime) -> int:
    """Số giây còn phải chờ cho header Retry-After: làm tròn lên, tối thiểu 1."""
    return max(1, math.ceil((until - now).total_seconds()))
