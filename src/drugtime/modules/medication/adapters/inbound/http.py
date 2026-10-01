from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel

from drugtime.modules.identity import api as identity
from drugtime.modules.medication.adapters.inbound.schemas import (
    UserMedication,
    UserMedicationCreate,
    UserMedicationUpdate,
)
from drugtime.modules.medication.adapters.outbound.other_modules import (
    AccessGuardAdapter,
    CatalogAdapter,
)
from drugtime.modules.medication.adapters.outbound.sql_medication import SqlMedication
from drugtime.modules.medication.application.create_medication import create_medication
from drugtime.modules.medication.application.get_medication import get_medication
from drugtime.modules.medication.application.update_medication import update_medication
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(prefix="/medications", tags=["medication"])

# TODO: GET /patients/{id}/schedules cho Mobile kéo lịch về (DM2) — task lịch uống.


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
MedicationId = Path(ge=1, description="Id thuốc của người bệnh (UserMedication.id)")


@router.post(
    "",
    status_code=201,
    response_model=UserMedication,
    responses={
        200: {"model": UserMedication, "description": "Gửi lại với client_uuid đã dùng"},
        **_ERRORS,
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
    )
    return UserMedication.from_view(view)
