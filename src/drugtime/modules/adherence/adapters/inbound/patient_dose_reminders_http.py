from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer
from pydantic import AwareDatetime

from drugtime.modules.adherence.adapters.inbound.http import ErrorDetail, NotificationUpdateRequest
from drugtime.modules.adherence.adapters.inbound.patient_dose_reminders_schemas import (
    DoseReminderCreate,
    DoseReminderReceipt,
    DoseReminderState,
    ReceivedDoseReminder,
    ReceivedDoseReminderPage,
)
from drugtime.modules.adherence.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    PatientNamesAdapter,
    SchedulesAdapter,
)
from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlDoseLogs
from drugtime.modules.adherence.adapters.outbound.sql_patient_dose_reminders import (
    SqlPatientDoseReminders,
)
from drugtime.modules.adherence.application.patient_dose_reminders import (
    received_detail,
    received_list,
    reminder_state,
    send_reminder,
)
from drugtime.modules.adherence.domain.patient_dose_reminder import ReminderCommand
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, unit_of_work
from drugtime.shared.errors import (
    Conflict,
    DomainError,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
)


class ReminderRoute(APIRoute):
    async def handle(self, scope, receive, send):
        async def no_store(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"
                ]
                message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        try:
            await super().handle(scope, receive, no_store)
        except (
            Conflict,
            DomainError,
            Forbidden,
            NotFound,
            ServiceUnavailable,
            TooManyRequests,
            Unauthorized,
        ) as exc:
            status = {
                Conflict: 409,
                DomainError: 422,
                Forbidden: 403,
                NotFound: 404,
                ServiceUnavailable: 503,
                TooManyRequests: 429,
                Unauthorized: 401,
            }[type(exc)]
            headers = {"Cache-Control": "no-store"}
            if isinstance(exc, TooManyRequests) and exc.retry_after is not None:
                headers["Retry-After"] = str(exc.retry_after)
            await JSONResponse({"detail": str(exc)}, status_code=status, headers=headers)(
                scope, receive, send
            )
        except Exception:
            await JSONResponse(
                {"detail": "service_unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)


def reminder_uow() -> Iterator[SqlUnitOfWork]:
    try:
        with unit_of_work() as uow:
            yield uow
    except (
        Conflict,
        DomainError,
        Forbidden,
        NotFound,
        TooManyRequests,
        Unauthorized,
        RequestValidationError,
    ):
        raise
    except Exception as exc:
        raise ServiceUnavailable("service_unavailable") from exc


Uow = Annotated[SqlUnitOfWork, Depends(reminder_uow, scope="function")]
User = Annotated[identity.CurrentUser, Depends(identity.current_user)]
ReminderId = Annotated[int, Path(ge=1, le=9223372036854775807)]
router = APIRouter(
    tags=["dose-reminders"],
    route_class=ReminderRoute,
    dependencies=[
        Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
    ],
)
HEALTH = {"x-health-scope": "lich_su_tuan_thu", "x-health-audit-self": True}
ERRORS = {code: {"model": ErrorDetail} for code in (401, 403, 422, 503)}


def _receipt(record):
    if record is None:
        return None
    return DoseReminderReceipt(**{k: getattr(record, k) for k in DoseReminderReceipt.model_fields})


def _received(value):
    record = value.record
    return ReceivedDoseReminder(
        **{
            k: getattr(record, k)
            for k in (
                "id",
                "patient_id",
                "schedule_id",
                "scheduled_at",
                "requested_at",
                "is_read",
                "status",
            )
        },
        medication_name=value.medication_name,
        sender_name=value.sender_name,
    )


def _ports():
    return dict(
        access=AccessGuardAdapter(), schedules=SchedulesAdapter(), store=SqlPatientDoseReminders()
    )


def _received_ports(user):
    return dict(
        user_id=user.id, caller_is_admin=user.is_admin, names=PatientNamesAdapter(), **_ports()
    )


@router.post(
    "/patients/{patient_id}/dose-reminders",
    operation_id="sendPatientDoseReminder",
    response_model=DoseReminderReceipt,
    status_code=201,
    openapi_extra=HEALTH,
    responses={
        **ERRORS,
        200: {"model": DoseReminderReceipt},
        409: {"model": ErrorDetail},
        429: {"model": ErrorDetail},
    },
)
def post_reminder(
    patient_id: UUID, body: DoseReminderCreate, response: Response, uow: Uow, user: User
):
    record, created = send_reminder(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        patient_id=patient_id,
        cmd=ReminderCommand(**body.model_dump()),
        doses=SqlDoseLogs(),
        **_ports(),
    )
    response.status_code = 201 if created else 200
    return _receipt(record)


@router.get(
    "/patients/{patient_id}/dose-reminders/status",
    operation_id="getPatientDoseReminderState",
    response_model=DoseReminderState,
    responses=ERRORS,
    openapi_extra=HEALTH,
)
def get_state(
    patient_id: UUID,
    uow: Uow,
    user: User,
    schedule_id: Annotated[int, Query(ge=1, le=9223372036854775807)],
    scheduled_at: AwareDatetime,
):
    record = reminder_state(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        patient_id=patient_id,
        schedule_id=schedule_id,
        scheduled_at=scheduled_at,
        **_ports(),
    )
    return DoseReminderState(
        patient_id=patient_id,
        schedule_id=schedule_id,
        scheduled_at=scheduled_at,
        last_reminder=_receipt(record),
    )


@router.get(
    "/dose-reminders/received",
    operation_id="listReceivedDoseReminders",
    response_model=ReceivedDoseReminderPage,
    responses=ERRORS,
    openapi_extra=HEALTH,
)
def get_received(
    uow: Uow,
    user: User,
    is_read: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total, unread = received_list(
        uow, is_read=is_read, limit=limit, offset=offset, **_received_ports(user)
    )
    return ReceivedDoseReminderPage(
        items=[_received(r) for r in items], total=total, unread_count=unread
    )


@router.get(
    "/dose-reminders/received/{id}",
    operation_id="getReceivedDoseReminder",
    response_model=ReceivedDoseReminder,
    responses={**ERRORS, 404: {"model": ErrorDetail}},
    openapi_extra=HEALTH,
)
def get_received_detail(id: ReminderId, uow: Uow, user: User):
    return _received(received_detail(uow, reminder_id=id, **_received_ports(user)))


@router.patch(
    "/dose-reminders/received/{id}",
    operation_id="updateReceivedDoseReminder",
    response_model=ReceivedDoseReminder,
    responses={**ERRORS, 404: {"model": ErrorDetail}},
    openapi_extra=HEALTH,
)
def patch_received(id: ReminderId, body: NotificationUpdateRequest, uow: Uow, user: User):
    return _received(
        received_detail(uow, reminder_id=id, is_read=body.is_read, **_received_ports(user))
    )
