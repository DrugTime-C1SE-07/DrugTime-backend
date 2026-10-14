"""Giao diện công khai của adherence."""

from datetime import timedelta
from uuid import UUID

from drugtime.modules.adherence.adapters.inbound.http import router
from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    DeviceTokensAdapter,
    SchedulesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import (
    SqlDoseLogs,
    SqlNotifications,
    SqlScanCursor,
)
from drugtime.modules.adherence.application import erase_user as _erase
from drugtime.modules.adherence.application import scan_missed_doses as _scan
from drugtime.modules.adherence.application.ports import NotificationPort
from drugtime.modules.adherence.domain.alert import Alert
from drugtime.shared.clock import now
from drugtime.shared.config import get_settings
from drugtime.shared.uow import UnitOfWork

__all__ = ["Alert", "NotificationPort", "eraser", "recorded_doses", "router", "scan_missed_doses"]

# Liều đã ghi, cho medication tính mốc hiệu lực khi sửa lịch; main.py nối vào medication.
recorded_doses = SqlDoseLogs()


def scan_missed_doses(uow_factory, *, notifier: NotificationPort) -> int:
    s = get_settings()
    return _scan.scan_and_notify(
        uow_factory,
        notifier,
        now=now(),
        grace=timedelta(minutes=s.missed_dose_grace_minutes),
        overlap=timedelta(minutes=s.missed_dose_overlap_minutes),
        cursor=SqlScanCursor(),
        schedules=SchedulesAdapter(),
        dose_logs=SqlDoseLogs(),
        access=AccessGuardAdapter(),
        tokens=DeviceTokensAdapter(),
        notifications=SqlNotifications(),
    )


class _Eraser:
    name = "adherence"

    def erase_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        _erase.erase_user(
            uow,
            user_id,
            schedules=SchedulesAdapter(),
            dose_logs=SqlDoseLogs(),
            notifications=SqlNotifications(),
        )


eraser = _Eraser()
