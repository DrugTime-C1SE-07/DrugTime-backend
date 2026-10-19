"""Quy tắc gửi yêu cầu liên kết (task 3.13): ngưỡng, giới hạn ngày, chặn sau từ chối (BS-04)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Bất biến 7: múi giờ cố định. Việt Nam không có giờ mùa hè nên offset +7 là đủ.
VIETNAM = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")


@dataclass(frozen=True)
class LinkRequestLimits:
    """Ngưỡng chống dò mã và gửi lại; adapter dựng từ Settings để đổi không cần sửa code."""

    fail_window: timedelta = timedelta(minutes=15)
    fail_account_limit: int = 5
    lock_duration: timedelta = timedelta(minutes=15)
    daily_request_limit: int = 10
    reject_streak_limit: int = 5
    reject_cooldown: timedelta = timedelta(hours=24)


def cooldown_until(
    streak: int, last_rejected_at: datetime | None, limits: LinkRequestLimits
) -> datetime | None:
    """Thời điểm hết chặn gửi lại sau `streak` lần bị từ chối liên tiếp (BS-04), hoặc None.

    Chặn khi chuỗi vừa đạt bội số của ngưỡng (5, 10, ...). Hết chặn thì lần từ chối kế tiếp
    làm chuỗi thành 6, không chặn: bộ đếm coi như về 0. Chấp thuận cắt chuỗi ở adapter.
    """
    if streak <= 0 or last_rejected_at is None or streak % limits.reject_streak_limit:
        return None
    return last_rejected_at + limits.reject_cooldown


def vn_day_start(now: datetime) -> datetime:
    """00:00 giờ Việt Nam của ngày chứa `now` (giới hạn yêu cầu theo ngày, QD-34 (e))."""
    local = now.astimezone(VIETNAM)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def next_vn_midnight(now: datetime) -> datetime:
    return vn_day_start(now) + timedelta(days=1)
