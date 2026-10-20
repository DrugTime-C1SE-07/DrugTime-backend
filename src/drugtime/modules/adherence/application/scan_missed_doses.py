from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta

from drugtime.modules.adherence.application.ports import (
    AccessGuard,
    DeviceTokens,
    DoseLogs,
    NotificationPort,
    Notifications,
    ScanCursor,
    Schedules,
)
from drugtime.modules.adherence.domain.alert import Alert, dedupe_key
from drugtime.modules.adherence.domain.dose import LATE_CONFIRMATION_WINDOW
from drugtime.shared.uow import UnitOfWork


def validate_grace(grace: timedelta) -> None:
    if grace != LATE_CONFIRMATION_WINDOW:
        raise ValueError("missed_dose_grace_minutes_must_be_120")


def scan(
    uow: UnitOfWork,
    *,
    now: datetime,
    grace: timedelta,
    overlap: timedelta,
    cursor: ScanCursor,
    schedules: Schedules,
    dose_logs: DoseLogs,
    access: AccessGuard,
    tokens: DeviceTokens,
    notifications: Notifications,
) -> list[Alert]:
    """DW1 bước 4–10, 13. Chồng lấn an toàn nhờ UPSERT và dedupe_key."""
    validate_grace(grace)
    until = now - LATE_CONFIRMATION_WINDOW
    previous = cursor.get(uow)
    start = min(previous or until, until) - overlap
    alerts: list[Alert] = []
    for occ in schedules.occurrences_between(uow, start, until):
        if now <= occ.scheduled_at + LATE_CONFIRMATION_WINDOW:
            continue
        dose_log_id = dose_logs.mark_missed(uow, occ.schedule_id, occ.scheduled_at)
        if dose_log_id is None:
            continue  # đã xác nhận, hoặc đã đánh dấu ở lượt quét trước
        created = {}
        for recipient_id in access.caregivers_of(uow, occ.patient_id):
            nid = notifications.create_missed_alert(
                uow, recipient_id, occ.patient_id, dedupe_key(dose_log_id, recipient_id)
            )
            if nid is not None:
                created[recipient_id] = nid
        # Người thân chỉ dùng iOS vẫn có dòng notifications và thấy khi mở app (DM3).
        for recipient_id, token in tokens.android_tokens(uow, list(created)):
            alerts.append(Alert(created[recipient_id], recipient_id, token))
    cursor.advance(uow, max(previous or until, until))
    return alerts


def scan_and_notify(
    uow_factory: Callable[[], AbstractContextManager[UnitOfWork]],
    notifier: NotificationPort,
    **ports,
) -> int:
    validate_grace(ports["grace"])
    with uow_factory() as uow:
        alerts = scan(uow, **ports)
    notifier.send(alerts)  # best effort, chỉ sau khi notifications đã commit (DW1 bước 11–12)
    return len(alerts)
