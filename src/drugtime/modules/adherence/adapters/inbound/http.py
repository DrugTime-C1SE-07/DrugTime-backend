from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, ConfigDict

from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    SchedulesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import (
    SqlDoseLogs,
    SqlNotifications,
)
from drugtime.modules.adherence.application.confirm_doses import confirm_doses
from drugtime.modules.adherence.application.manage_notifications import (
    list_my_notifications,
    update_notification_status,
)
from drugtime.modules.adherence.domain.dose import DoseConfirmation
from drugtime.modules.identity import api as identity
from drugtime.shared.clock import now
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(tags=["adherence"])


class DoseConfirmationIn(BaseModel):
    client_uuid: UUID
    schedule_id: int
    scheduled_at: datetime
    taken_at: datetime


class DoseConfirmationItemErrorOut(BaseModel):
    code: str
    http_status: int
    detail: str


class DoseConfirmationResultOut(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    client_uuid: UUID
    schedule_id: int
    scheduled_at: datetime
    result: str
    dose_log_id: int | None = None
    dose_status: str | None = None
    adherence_counted: bool | None = None
    synced_at: datetime | None = None
    error: DoseConfirmationItemErrorOut | None = None


class DoseConfirmationSummaryOut(BaseModel):
    total: int
    synced: int
    failed: int


class DoseConfirmationBatchOut(BaseModel):
    items: list[DoseConfirmationResultOut]
    summary: DoseConfirmationSummaryOut


@router.post(
    "/doses/batch",
    response_model=DoseConfirmationBatchOut,
    response_model_exclude_none=True,
)
def post_doses(
    items: Annotated[list[DoseConfirmationIn], Body(min_length=1, max_length=50)],
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> DoseConfirmationBatchOut:
    result = confirm_doses(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        items=[DoseConfirmation(**i.model_dump()) for i in items],
        now=now(),
        access=AccessGuardAdapter(),
        schedules=SchedulesAdapter(),
        dose_logs=SqlDoseLogs(),
    )
    return DoseConfirmationBatchOut(
        items=[
            DoseConfirmationResultOut(
                client_uuid=item.client_uuid,
                schedule_id=item.schedule_id,
                scheduled_at=item.scheduled_at,
                result=item.result,
                dose_log_id=item.dose_log_id,
                dose_status=item.dose_status.value if item.dose_status is not None else None,
                adherence_counted=item.adherence_counted,
                synced_at=item.synced_at,
                error=(
                    None
                    if item.error is None
                    else DoseConfirmationItemErrorOut(
                        code=item.error.code,
                        http_status=item.error.http_status,
                        detail=item.error.detail,
                    )
                ),
            )
            for item in result.items
        ],
        summary=DoseConfirmationSummaryOut(
            total=result.total,
            synced=result.synced,
            failed=result.failed,
        ),
    )


class NotificationType(StrEnum):
    MISSED_DOSE_CARE_ALERT = "canh_bao_bo_lo_lieu_nguoi_than"


class NotificationItemOut(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int
    type: NotificationType
    title: str
    content: str
    is_read: bool
    about_patient_user_id: UUID | None
    about_patient_name: str | None
    created_at: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationItemOut]
    total: int
    unread_count: int


class NotificationUpdateRequest(BaseModel):
    is_read: bool


class ErrorDetail(BaseModel):
    detail: str


_ERRORS = {
    401: {"model": ErrorDetail, "description": "Chưa xác thực"},
}
_NOT_FOUND = {
    404: {"model": ErrorDetail, "description": "notification_not_found"},
}


@router.get(
    "/notifications",
    response_model=NotificationListOut,
    responses={**_ERRORS},
    tags=["notification"],
    operation_id="listMyNotifications",
    summary="Lấy danh sách thông báo của chính người gọi",
)
def get_notifications(
    is_read: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> NotificationListOut:
    result = list_my_notifications(
        uow,
        user_id=user.id,
        is_read=is_read,
        limit=limit,
        offset=offset,
        notifications=SqlNotifications(),
    )
    return NotificationListOut(
        items=[
            NotificationItemOut(
                id=item.id,
                type=NotificationType(item.type),
                title="DrugTime",
                content=item.content,
                is_read=item.is_read,
                about_patient_user_id=item.about_patient_user_id,
                about_patient_name=item.about_patient_name,
                created_at=item.created_at,
            )
            for item in result.items
        ],
        total=result.total,
        unread_count=result.unread_count,
    )


@router.patch(
    "/notifications/{id}",
    response_model=NotificationItemOut,
    responses={**_ERRORS, **_NOT_FOUND},
    tags=["notification"],
    operation_id="updateNotificationStatus",
    summary="Cập nhật trạng thái đã đọc của thông báo",
)
def patch_notification(
    id: Annotated[int, Path(ge=1)],
    body: NotificationUpdateRequest,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> NotificationItemOut:
    record = update_notification_status(
        uow,
        user_id=user.id,
        notification_id=id,
        is_read=body.is_read,
        notifications=SqlNotifications(),
    )
    return NotificationItemOut(
        id=record.id,
        type=NotificationType(record.type),
        title="DrugTime",
        content=record.content,
        is_read=record.is_read,
        about_patient_user_id=record.about_patient_user_id,
        about_patient_name=record.about_patient_name,
        created_at=record.created_at,
    )
