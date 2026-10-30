from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict

from drugtime.modules.adherence.adapters.inbound.history_http import router as history_router
from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    PatientNamesAdapter,
    SchedulesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import (
    SqlDoseLogs,
    SqlNotifications,
    SqlSyncCheckpoints,
)
from drugtime.modules.adherence.application.confirm_doses import confirm_doses
from drugtime.modules.adherence.application.manage_notifications import (
    get_notification,
    list_my_notifications,
    update_notification_status,
)
from drugtime.modules.adherence.application.record_sync_checkpoint import record_sync_checkpoint
from drugtime.modules.adherence.domain.dose import DoseConfirmation
from drugtime.modules.identity import api as identity
from drugtime.shared.clock import now
from drugtime.shared.db import SqlUnitOfWork, get_uow, unit_of_work
from drugtime.shared.errors import Forbidden, NotFound, ServiceUnavailable, Unauthorized

router = APIRouter(tags=["adherence"])
router.include_router(history_router)
_BEARER = Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))


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
    operation_id="confirmDoseBatch",
    dependencies=[_BEARER],
    openapi_extra={"x-health-scope": "lich_su_tuan_thu", "x-health-audit-self": False},
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


def get_checkpoint_uow() -> Iterator[SqlUnitOfWork]:
    try:
        with unit_of_work() as uow:
            yield uow
    except (Forbidden, Unauthorized, RequestValidationError):
        raise
    except Exception as exc:
        raise ServiceUnavailable("service_unavailable") from exc


# PEP và ghi checkpoint commit trước khi gửi response: lỗi commit trả 503 thay vì 204 đã gửi.
CheckpointUow = Annotated[SqlUnitOfWork, Depends(get_checkpoint_uow, scope="function")]


@router.post(
    "/doses/sync-checkpoints",
    status_code=204,
    response_class=Response,
    operation_id="recordDoseSyncCheckpoint",
    dependencies=[_BEARER],
    openapi_extra={"x-health-scope": "lich_su_tuan_thu", "x-health-audit-self": False},
)
def post_sync_checkpoint(
    uow: CheckpointUow,
    user: identity.CurrentUser = Depends(identity.current_user),
) -> Response:
    record_sync_checkpoint(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        access=AccessGuardAdapter(),
        checkpoints=SqlSyncCheckpoints(),
    )
    return Response(status_code=204)


class NotificationRoute(APIRoute):
    async def handle(self, scope, receive, send):
        # Function-scoped dependencies commit outside get_route_handler in FastAPI.
        # Cover the whole route so commit failures also carry no-store.
        async def no_store_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"
                ]
                message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        try:
            await super().handle(scope, receive, no_store_send)
        except (Forbidden, NotFound, Unauthorized, ServiceUnavailable) as exc:
            status = {Forbidden: 403, NotFound: 404, Unauthorized: 401, ServiceUnavailable: 503}[
                type(exc)
            ]
            await JSONResponse(
                {"detail": str(exc)}, status_code=status, headers={"Cache-Control": "no-store"}
            )(scope, receive, send)
        except Exception:
            # Outside the dependency stack: the transaction has rolled back first.
            await JSONResponse(
                {"detail": "notification_access_unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)


def get_notification_uow() -> Iterator[SqlUnitOfWork]:
    try:
        with unit_of_work() as uow:
            yield uow
    except (Forbidden, NotFound, Unauthorized, RequestValidationError):
        raise
    except Exception as exc:
        raise ServiceUnavailable("notification_access_unavailable") from exc


# Kết thúc transaction trước khi gửi response để lỗi commit audit vẫn trả được 503.
NotificationUow = Annotated[SqlUnitOfWork, Depends(get_notification_uow, scope="function")]


# Xác thực và đọc cảnh báo dùng chung UoW của request, tránh hai transaction độc lập.
def notification_user(uow: NotificationUow, authorization: str | None = Header(None)):
    return identity.current_user(authorization=authorization, uow=uow)


NotificationUser = Annotated[identity.CurrentUser, Depends(notification_user)]
NotificationId = Annotated[
    int, Path(ge=1, le=9223372036854775807, json_schema_extra={"format": "int64"})
]


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
    medication_name: str | None
    scheduled_at: datetime | None


class NotificationListOut(BaseModel):
    items: list[NotificationItemOut]
    total: int
    unread_count: int


class NotificationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_read: bool


class ErrorDetail(BaseModel):
    detail: str


_ERRORS = {code: {"model": ErrorDetail} for code in (401, 403, 503)}
_NOT_FOUND = {404: {"model": ErrorDetail}}
notification_router = APIRouter(tags=["notification"], route_class=NotificationRoute)


def _ports(user):
    return dict(
        user_id=user.id,
        caller_is_admin=user.is_admin,
        notifications=SqlNotifications(),
        access=AccessGuardAdapter(),
        patient_names=PatientNamesAdapter(),
    )


def _item(record):
    return NotificationItemOut(
        id=record.id,
        type=record.type,
        title="DrugTime",
        content=record.content,
        is_read=record.is_read,
        about_patient_user_id=record.about_patient_user_id,
        about_patient_name=record.about_patient_name,
        created_at=record.created_at,
        medication_name=record.medication_name,
        scheduled_at=record.scheduled_at,
    )


@notification_router.get(
    "/notifications",
    response_model=NotificationListOut,
    responses=_ERRORS,
    operation_id="listMyNotifications",
)
def get_notifications(
    uow: NotificationUow,
    user: NotificationUser,
    is_read: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    result = list_my_notifications(uow, is_read=is_read, limit=limit, offset=offset, **_ports(user))
    return NotificationListOut(
        items=[_item(r) for r in result.items], total=result.total, unread_count=result.unread_count
    )


@notification_router.get(
    "/notifications/{id}",
    response_model=NotificationItemOut,
    responses={**_ERRORS, **_NOT_FOUND},
    operation_id="getMyNotification",
)
def get_notification_detail(id: NotificationId, uow: NotificationUow, user: NotificationUser):
    return _item(get_notification(uow, notification_id=id, **_ports(user)))


@notification_router.patch(
    "/notifications/{id}",
    response_model=NotificationItemOut,
    responses={**_ERRORS, **_NOT_FOUND},
    operation_id="updateNotificationStatus",
)
def patch_notification(
    id: NotificationId,
    body: NotificationUpdateRequest,
    uow: NotificationUow,
    user: NotificationUser,
):
    return _item(
        update_notification_status(uow, notification_id=id, is_read=body.is_read, **_ports(user))
    )


router.include_router(notification_router)
