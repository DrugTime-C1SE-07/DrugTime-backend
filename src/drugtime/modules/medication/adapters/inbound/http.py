from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel

from drugtime.modules.identity import api as identity
from drugtime.modules.medication.adapters.inbound.schemas import (
    MedicationScheduleCreate,
    MedicationScheduleUpdate,
    PatientSchedule,
    PatientScheduleList,
    UserMedication,
    UserMedicationCreate,
    UserMedicationList,
    UserMedicationUpdate,
)
from drugtime.modules.medication.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    CatalogAdapter,
)
from drugtime.modules.medication.adapters.outbound.sql_medication import SqlMedication
from drugtime.modules.medication.application.create_medication import create_medication
from drugtime.modules.medication.application.delete_medication import delete_medication
from drugtime.modules.medication.application.get_medication import get_medication
from drugtime.modules.medication.application.list_medications import list_medications
from drugtime.modules.medication.application.list_patient_schedules import (
    list_patient_schedules,
)
from drugtime.modules.medication.application.manage_schedules import (
    add_schedule,
    remove_schedule,
    update_schedule,
)
from drugtime.modules.medication.application.ports import RecordedDoses
from drugtime.modules.medication.application.update_medication import update_medication
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(prefix="/medications", tags=["medication"])
patients_router = APIRouter(prefix="/patients", tags=["medication"])

# Port liều đã ghi (hiện thực ở adherence), do composition root nối qua medication.api.configure.
_recorded_doses: RecordedDoses | None = None


def set_recorded_doses(port: RecordedDoses) -> None:
    global _recorded_doses
    _recorded_doses = port


def recorded_doses() -> RecordedDoses:
    """Chưa nối thì lỗi, không âm thầm bỏ qua mốc hiệu lực theo liều xác nhận sớm (QD-16)."""
    if _recorded_doses is None:
        raise RuntimeError("medication.configure(recorded_doses=...) chưa được gọi")
    return _recorded_doses


class ErrorDetail(BaseModel):
    detail: str


_ERRORS = {
    401: {"model": ErrorDetail, "description": "Chưa xác thực"},
    403: {"model": ErrorDetail, "description": "khong_co_quyen | consent_revoked"},
}
_NOT_FOUND = {404: {"model": ErrorDetail, "description": "user_medication_not_found"}}
_UNPROCESSABLE = {
    422: {
        "description": "ValidationError, hoặc ErrorDetail với catalog_medication_not_found | "
        "medication_rule_violation | medication_stopped"
    }
}
_SCHEDULE_NOT_FOUND = {
    404: {
        "model": ErrorDetail,
        "description": "user_medication_not_found | medication_schedule_not_found",
    }
}
_SCHEDULE_UNPROCESSABLE = {
    422: {
        "description": "ValidationError, hoặc ErrorDetail với medication_stopped | "
        "medication_rule_violation | schedule_time_conflict | schedule_limit_reached | "
        "last_schedule_not_removable"
    }
}
MedicationId = Path(ge=1, description="Id thuốc của người bệnh (UserMedication.id)")
ScheduleId = Path(ge=1, description="Id lịch đang mở của thuốc (MedicationSchedule.id)")


@router.get(
    "",
    response_model=UserMedicationList,
    responses=_ERRORS,
    operation_id="listUserMedications",
)
def get_user_medications(
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> UserMedicationList:
    views = list_medications(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        access=AccessGuardAdapter(),
        catalog=CatalogAdapter(),
        meds=SqlMedication(),
    )
    return UserMedicationList(items=[UserMedication.from_view(v) for v in views])


@router.post(
    "",
    status_code=201,
    response_model=UserMedication,
    responses={
        200: {"model": UserMedication, "description": "Gửi lại với client_uuid đã dùng"},
        **_ERRORS,
        404: {
            "model": ErrorDetail,
            "description": "user_medication_not_found: gửi lại client_uuid của thuốc đã xoá",
        },
        **_UNPROCESSABLE,
    },
    operation_id="createUserMedication",
)
def post_medication(
    body: UserMedicationCreate,
    response: Response,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> UserMedication:
    view, created = create_medication(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        cmd=body.to_domain(),
        access=AccessGuardAdapter(),
        catalog=CatalogAdapter(),
        meds=SqlMedication(),
    )
    response.status_code = 201 if created else 200
    response.headers["Location"] = f"/medications/{view.record.id}"
    return UserMedication.from_view(view)


@router.get(
    "/{id}",
    response_model=UserMedication,
    responses={**_ERRORS, **_NOT_FOUND},
    operation_id="getUserMedication",
)
def get_user_medication(
    id: int = MedicationId,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> UserMedication:
    view = get_medication(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        user_medication_id=id,
        access=AccessGuardAdapter(),
        catalog=CatalogAdapter(),
        meds=SqlMedication(),
    )
    return UserMedication.from_view(view)


@router.patch(
    "/{id}",
    response_model=UserMedication,
    responses={**_ERRORS, **_NOT_FOUND, **_UNPROCESSABLE},
    operation_id="updateUserMedication",
)
def patch_user_medication(
    body: UserMedicationUpdate,
    id: int = MedicationId,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
    recorded: RecordedDoses = Depends(recorded_doses),
) -> UserMedication:
    view = update_medication(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        user_medication_id=id,
        changes=body.to_domain(),
        access=AccessGuardAdapter(),
        catalog=CatalogAdapter(),
        meds=SqlMedication(),
        recorded=recorded,
    )
    return UserMedication.from_view(view)


@router.delete(
    "/{id}",
    status_code=204,
    response_class=Response,
    responses={**_ERRORS, **_NOT_FOUND},
    operation_id="deleteUserMedication",
)
def delete_user_medication(
    id: int = MedicationId,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
    recorded: RecordedDoses = Depends(recorded_doses),
) -> Response:
    delete_medication(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        user_medication_id=id,
        access=AccessGuardAdapter(),
        meds=SqlMedication(),
        recorded=recorded,
    )
    return Response(status_code=204)


# --- Lịch uống (task 2.04) -----------------------------------------------------------------


@router.post(
    "/{id}/schedules",
    status_code=201,
    response_model=UserMedication,
    responses={**_ERRORS, **_NOT_FOUND, **_SCHEDULE_UNPROCESSABLE},
    operation_id="addMedicationSchedule",
)
def post_medication_schedule(
    body: MedicationScheduleCreate,
    id: int = MedicationId,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
    recorded: RecordedDoses = Depends(recorded_doses),
) -> UserMedication:
    view = add_schedule(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        user_medication_id=id,
        intake_time=body.to_time(),
        reminder_enabled=body.reminder_enabled,
        access=AccessGuardAdapter(),
        catalog=CatalogAdapter(),
        meds=SqlMedication(),
        recorded=recorded,
    )
    return UserMedication.from_view(view)


@router.patch(
    "/{id}/schedules/{schedule_id}",
    response_model=UserMedication,
    responses={**_ERRORS, **_SCHEDULE_NOT_FOUND, **_SCHEDULE_UNPROCESSABLE},
    operation_id="updateMedicationSchedule",
)
def patch_medication_schedule(
    body: MedicationScheduleUpdate,
    id: int = MedicationId,
    schedule_id: int = ScheduleId,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
    recorded: RecordedDoses = Depends(recorded_doses),
) -> UserMedication:
    view = update_schedule(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        user_medication_id=id,
        schedule_id=schedule_id,
        intake_time=body.to_time(),
        reminder_enabled=body.reminder_enabled,
        access=AccessGuardAdapter(),
        catalog=CatalogAdapter(),
        meds=SqlMedication(),
        recorded=recorded,
    )
    return UserMedication.from_view(view)


@router.delete(
    "/{id}/schedules/{schedule_id}",
    response_model=UserMedication,
    responses={**_ERRORS, **_SCHEDULE_NOT_FOUND, **_SCHEDULE_UNPROCESSABLE},
    operation_id="removeMedicationSchedule",
)
def delete_medication_schedule(
    id: int = MedicationId,
    schedule_id: int = ScheduleId,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
    recorded: RecordedDoses = Depends(recorded_doses),
) -> UserMedication:
    view = remove_schedule(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        user_medication_id=id,
        schedule_id=schedule_id,
        access=AccessGuardAdapter(),
        catalog=CatalogAdapter(),
        meds=SqlMedication(),
        recorded=recorded,
    )
    return UserMedication.from_view(view)


@patients_router.get(
    "/{patient_id}/schedules",
    response_model=PatientScheduleList,
    responses={
        **_ERRORS,
        422: {"description": "ValidationError (patient_id, limit) | ErrorDetail invalid_cursor"},
    },
    operation_id="listPatientSchedules",
)
def get_patient_schedules(
    patient_id: UUID,
    limit: int = Query(100, ge=1, le=200, description="Số lịch tối đa của trang."),
    # Kiểu str, mặc định None: không gửi được chấp nhận, gửi chuỗi rỗng bị 422 (như contract).
    cursor: str = Query(None, min_length=1, max_length=200, description="next_cursor trang trước."),
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> PatientScheduleList:
    page = list_patient_schedules(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        patient_id=patient_id,
        limit=limit,
        cursor=cursor,
        access=AccessGuardAdapter(),
        catalog=CatalogAdapter(),
        meds=SqlMedication(),
    )
    return PatientScheduleList(
        items=[PatientSchedule.from_view(v) for v in page.items], next_cursor=page.next_cursor
    )
