import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from drugtime.modules.adherence.application.ports import (
    AccessGuard,
    DeviceTokens,
    DoseLogs,
    NotificationPort,
    Notifications,
    PatientNames,
    PendingVerifications,
    ScanCursor,
    Schedules,
    SyncCheckpoints,
)
from drugtime.modules.adherence.domain.alert import Alert, SyncRequest, dedupe_key
from drugtime.modules.adherence.domain.dose import LATE_CONFIRMATION_WINDOW
from drugtime.shared.uow import UnitOfWork

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    alerts: list[Alert] = field(default_factory=list)
    sync_requests: list[SyncRequest] = field(default_factory=list)


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
    checkpoints: SyncCheckpoints,
    pending: PendingVerifications,
    patient_names: PatientNames | None = None,
) -> ScanResult:
    """DW1 bước 4–10, 13, có xác minh (3.19): chỉ ghi bo_lo khi checkpoint của patient >= hạn chót.
    Chồng lấn an toàn nhờ UPSERT, dedupe_key và khóa chính của hàng chờ xác minh."""
    validate_grace(grace)
    until = now - LATE_CONFIRMATION_WINDOW
    previous = cursor.get(uow)
    start = min(previous or until, until) - overlap
    if patient_names is None:
        from drugtime.modules.adherence.adapters.outbound.other_modules import PatientNamesAdapter

        patient_names = PatientNamesAdapter()

    def record_missed(occ) -> list[Alert]:
        dose_log_id = dose_logs.mark_missed(uow, occ.schedule_id, occ.scheduled_at)
        if dose_log_id is None:
            return []  # đã xác nhận, hoặc đã đánh dấu ở lượt quét trước
        return _alert_family(
            uow, occ, dose_log_id, schedules, access, tokens, notifications, patient_names
        )

    occurrences = [
        occ
        for occ in schedules.occurrences_between(uow, start, until)
        if now > occ.scheduled_at + LATE_CONFIRMATION_WINDOW
    ]
    synced = checkpoints.get_many(uow, list(dict.fromkeys(o.patient_id for o in occurrences)))
    alerts: list[Alert] = []
    knock: dict = {}
    # (a) Liều mới qua hạn chót: xác minh được thì ghi bo_lo, chưa thì vào hàng chờ và gõ cửa.
    for occ in occurrences:
        synced_at = synced.get(occ.patient_id)
        if synced_at is not None and synced_at >= occ.scheduled_at + LATE_CONFIRMATION_WINDOW:
            alerts.extend(record_missed(occ))
        elif pending.add(uow, occ):
            knock[occ.patient_id] = (
                None  # chỉ liều vừa vào hàng mới gõ, nên quét chồng lấn không gõ lại
            )
    # (b) Liều chưa xác minh từ các lượt trước, nay patient đã đồng bộ sau hạn chót.
    for occ in pending.verified(uow, now):
        alerts.extend(record_missed(occ))
        pending.remove(uow, occ)
    # (c) Liều trong hàng đã có xác nhận thì không còn gì để xác minh.
    pending.purge_recorded(uow)
    cursor.advance(uow, max(previous or until, until))
    sync_requests = (
        [
            SyncRequest(patient_id=patient_id, device_token=token)
            for patient_id, token in tokens.android_tokens(uow, list(knock))
        ]
        if knock
        else []
    )
    return ScanResult(alerts=alerts, sync_requests=sync_requests)


def _alert_family(
    uow, occ, dose_log_id, schedules, access, tokens, notifications, patient_names
) -> list[Alert]:
    # Snapshot gắn với occurrence gây cảnh báo, không dùng giờ tạo notification.
    medication_name = schedules.alert_context(uow, occ.schedule_id, occ.patient_id)
    if (
        not isinstance(medication_name, str)
        or not medication_name.strip()
        or occ.scheduled_at.utcoffset() is None
    ):
        # Ném lỗi để UoW rollback cả liều bỏ lỡ, notification và cursor của lượt quét.
        raise ValueError("notification event snapshot unavailable")
    patient_name = patient_names.get_patient_name(uow, occ.patient_id) if patient_names else None
    # Hộp thư (sau PEP) có tên patient; thân push giữ câu chung mặc định của Alert (QD-26).
    if patient_name:
        content = f"Bác {patient_name} chưa ghi nhận liều thuốc đúng giờ"
    else:
        content = "Chưa ghi nhận liều thuốc đúng giờ"

    created = {}
    for recipient_id in access.caregivers_of(uow, occ.patient_id):
        nid = notifications.create_missed_alert(
            uow,
            recipient_id,
            occ.patient_id,
            dedupe_key(dose_log_id, recipient_id),
            content=content,
            medication_name=medication_name,
            scheduled_at=occ.scheduled_at,
        )
        if nid is not None:
            created[recipient_id] = nid

    # iOS vẫn có dòng notifications khi mở app (DM3, C-06, C-07, BS-03).
    return [
        Alert(notification_id=created[recipient_id], recipient_id=recipient_id, device_token=token)
        for recipient_id, token in tokens.android_tokens(uow, list(created))
    ]


def scan_and_notify(
    uow_factory: Callable[[], AbstractContextManager[UnitOfWork]],
    notifier: NotificationPort,
    **ports,
) -> int:
    validate_grace(ports["grace"])
    with uow_factory() as uow:
        result = scan(uow, **ports)
    # Best effort, chỉ sau khi notifications và hàng chờ đã commit (DW1 bước 11–12).
    unregistered: list[str] = []
    if result.alerts:
        unregistered += _dispatch("alerts", lambda: notifier.send(result.alerts))
    if result.sync_requests:
        unregistered += _dispatch(
            "sync_requests", lambda: notifier.request_sync(result.sync_requests)
        )
    if unregistered:
        _remove_unregistered(uow_factory, ports["tokens"], unregistered)
    return len(result.alerts)


def _dispatch(kind: str, send: Callable[[], list[str] | None]) -> list[str]:
    # Lỗi một loại push không chặn loại kia; gateway đã log từng token mà không kèm token.
    try:
        return list(send() or [])
    except Exception:
        log.exception("push dispatch failed for %s", kind)
        return []


def _remove_unregistered(uow_factory, tokens: DeviceTokens, unregistered: list[str]) -> None:
    try:
        with uow_factory() as uow:
            tokens.remove(uow, sorted(set(unregistered)))
    except Exception:
        # Token còn lại chỉ làm lần gửi sau lỗi lại; không log token.
        log.exception("removing %d unregistered device token(s) failed", len(set(unregistered)))
