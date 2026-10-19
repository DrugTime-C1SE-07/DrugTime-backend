from dataclasses import dataclass
from uuid import UUID

from drugtime.modules.adherence.application.ports import Notifications
from drugtime.modules.adherence.domain.alert import NotificationRecord
from drugtime.shared.errors import NotFound
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class NotificationListResult:
    items: list[NotificationRecord]
    total: int
    unread_count: int


def list_my_notifications(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_read: bool | None,
    limit: int,
    offset: int,
    notifications: Notifications,
) -> NotificationListResult:
    items, total, unread = notifications.list_for_user(
        uow,
        user_id=user_id,
        is_read=is_read,
        limit=limit,
        offset=offset,
    )
    return NotificationListResult(items=items, total=total, unread_count=unread)


def update_notification_status(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    notification_id: int,
    is_read: bool,
    notifications: Notifications,
) -> NotificationRecord:
    record = notifications.mark_as_read(
        uow,
        notification_id=notification_id,
        user_id=user_id,
        is_read=is_read,
    )
    if record is None:
        raise NotFound("notification_not_found")
    return record
