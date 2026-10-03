from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from drugtime.modules.consent.adapters.inbound.schemas import (
    Consent,
    ConsentGrantRequest,
    ConsentList,
)
from drugtime.modules.consent.adapters.outbound.sql_consent import SqlConsents
from drugtime.modules.consent.application.manage_consents import (
    grant_consent,
    list_consents,
    withdraw_consent,
)
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(tags=["consent"])


class ErrorDetail(BaseModel):
    detail: str


_UNAUTHORIZED = {401: {"model": ErrorDetail, "description": "Chưa xác thực"}}


# Chỉ thao tác trên consent của chính người gọi: không nhận user_id/patient_id, không có dữ
# liệu sức khỏe, nên không đi qua PEP và không ghi access_logs (chính chủ không ghi log).
@router.get(
    "/consents",
    response_model=ConsentList,
    responses=_UNAUTHORIZED,
    operation_id="listMyConsents",
)
def list_my_consents(
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> ConsentList:
    states = list_consents(uow, user_id=user.id, store=SqlConsents())
    return ConsentList(items=[Consent.from_state(s) for s in states])


@router.post(
    "/consents",
    status_code=201,
    response_model=Consent,
    responses={
        200: {"model": Consent, "description": "Mục đích đã có consent hiệu lực"},
        **_UNAUTHORIZED,
        422: {"description": "ValidationError, hoặc ErrorDetail consent_document_outdated"},
    },
    operation_id="grantConsent",
)
def post_consent(
    body: ConsentGrantRequest,
    response: Response,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> Consent:
    state, created = grant_consent(
        uow,
        user_id=user.id,
        purpose=body.purpose,
        document_version=body.document_version,
        store=SqlConsents(),
    )
    response.status_code = 201 if created else 200
    return Consent.from_state(state)


@router.post(
    "/consents/{purpose}/withdraw",
    response_model=Consent,
    responses={**_UNAUTHORIZED, 422: {"description": "purpose không hợp lệ"}},
    operation_id="withdrawConsent",
)
def post_withdraw_consent(
    purpose: Purpose,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> Consent:
    state = withdraw_consent(uow, user_id=user.id, purpose=purpose, store=SqlConsents())
    return Consent.from_state(state)


# TODO: POST /deletion-requests, Admin: GET /admin/deletion-requests,
#       POST /admin/deletion-requests/{id}/approve
#       (approve: set da_duyet trong transaction, rồi job_queue.enqueue_erasure)
