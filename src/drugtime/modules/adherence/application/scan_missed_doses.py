from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta

from drugtime.modules.adherence.application.ports import (
    AccessGuard,
    DeviceTokens,
    DoseLogs,
    NotificationPort,
    Notifications,
    PatientNames,
    ScanCursor,
    Schedules,
)
from drugtime.modules.adherence.domain.alert import Alert, dedupe_key
from drugtime.shared.uow import UnitOfWork


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
    patient_names: PatientNames | None = None,
) -> list[Alert]:
    """DW1 bước 4–10, 13. Chồng lấn an toàn nhờ UPSERT và dedupe_key."""
    until = now - grace
    start = (cursor.get(uow) or until) - overlap
    if patient_names is None:
        from drugtime.modules.adherence.adapters.outbound.other_modules import PatientNamesAdapter

        patient_names = PatientNamesAdapter()
    alerts: list[Alert] = []
    for occ in schedules.occurrences_between(uow, start, until):
        dose_log_id = dose_logs.mark_missed(uow, occ.schedule_id, occ.scheduled_at)
        if dose_log_id is None:
            continue  # đã xác nhận, hoặc đã đánh dấu ở lượt quét trước

        patient_name = patient_names.get_patient_name(uow, occ.patient_id) if patient_names else None
        if patient_name:
            content = f"Bác {patient_name} chưa ghi nhận liều thuốc đúng giờ"
            alert_body = f"Bác {patient_name} chưa ghi nhận liều thuốc đúng giờ"
        else:
            content = "Chưa ghi nhận liều thuốc đúng giờ"
            alert_body = "Bạn có cảnh báo mới về người thân"

        created = {}
        for recipient_id in access.caregivers_of(uow, occ.patient_id):
            nid = notifications.create_missed_alert(
                uow,
                recipient_id,
                occ.patient_id,
                dedupe_key(dose_log_id, recipient_id),
                content=content,
            )
            if nid is not None:
                created[recipient_id] = nid

        # Người thân chỉ dùng iOS vẫn có dòng notifications và thấy khi mở app (DM3, C-06, C-07, BS-03).
        for recipient_id, token in tokens.android_tokens(uow, list(created)):
            alerts.append(
                Alert(
                    notification_id=created[recipient_id],
                    recipient_id=recipient_id,
                    device_token=token,
                    title="DrugTime",
                    body=alert_body,
                )
            )
    cursor.advance(uow, until)
    return alerts


def scan_and_notify(
    uow_factory: Callable[[], AbstractContextManager[UnitOfWork]],
    notifier: NotificationPort,
    **ports,
) -> int:
    with uow_factory() as uow:
        alerts = scan(uow, **ports)
    notifier.send(alerts)  # best effort, chỉ sau khi notifications đã commit (DW1 bước 11–12)
    return len(alerts)
