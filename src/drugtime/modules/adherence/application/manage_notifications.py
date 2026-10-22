from dataclasses import dataclass, replace
from uuid import UUID

from drugtime.modules.adherence.application.ports import AccessGuard, Notifications, PatientNames
from drugtime.modules.adherence.domain.alert import NotificationRecord
from drugtime.shared.errors import Forbidden, NotFound, ServiceUnavailable
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class NotificationListResult:
    items: list[NotificationRecord]
    total: int
    unread_count: int


def _authorize(uow, user_id, patient_id, access):
    try:
        access.authorize_adherence(uow, user_id, False, patient_id)
    except Forbidden:
        # PEP raises Forbidden only after its independent denied audit succeeds.
        raise
    except Exception as exc:
        raise ServiceUnavailable("notification_access_unavailable") from exc


def _named(uow, record, patient_names):
    return replace(
        record, about_patient_name=patient_names.get_patient_name(uow, record.about_patient_user_id)
    )


def list_my_notifications(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_read: bool | None,
    limit: int,
    offset: int,
    notifications: Notifications,
    access: AccessGuard,
    patient_names: PatientNames,
    caller_is_admin: bool = False,
) -> NotificationListResult:
    if caller_is_admin:
        raise Forbidden("khong_co_quyen")
    # Quyền chỉ có hiệu lực trong request này; mỗi patient được kiểm qua PEP một lần.
    metadata = notifications.metadata(uow, user_id)
    allowed = set()
    for patient in dict.fromkeys(patient for _, patient in metadata):
        try:
            _authorize(uow, user_id, patient, access)
        except Forbidden:
            continue
        allowed.add(patient)
    records = notifications.authorized_records(
        uow, user_id, [nid for nid, patient in metadata if patient in allowed]
    )
    # Lọc quyền trước count/phân trang; badge chưa đọc độc lập với bộ lọc is_read.
    unread = sum(not r.is_read for r in records)
    matched = [r for r in records if is_read is None or r.is_read == is_read]
    return NotificationListResult(
        [_named(uow, r, patient_names) for r in matched[offset : offset + limit]],
        len(matched),
        unread,
    )


def get_notification(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    notification_id: int,
    notifications: Notifications,
    access: AccessGuard,
    patient_names: PatientNames,
    caller_is_admin: bool = False,
    is_read: bool | None = None,
) -> NotificationRecord:
    if caller_is_admin:
        raise Forbidden("khong_co_quyen")
    # Tra theo recipient trước để ID của hộp thư khác cũng trả 404, không lộ patient.
    metadata = notifications.metadata(uow, user_id, notification_id)
    if not metadata:
        raise NotFound("notification_not_found")
    _authorize(uow, user_id, metadata[0][1], access)
    # Cả đọc chi tiết lẫn PATCH metadata đều phải qua cùng bước kiểm quyền phía trên.
    if is_read is None:
        records = notifications.authorized_records(uow, user_id, [notification_id])
        record = records[0] if records else None
    else:
        record = notifications.mark_as_read(uow, notification_id, user_id, is_read)
    if record is None:
        raise NotFound("notification_not_found")
    return _named(uow, record, patient_names)


def update_notification_status(uow: UnitOfWork, **kwargs) -> NotificationRecord:
    return get_notification(uow, **kwargs)
