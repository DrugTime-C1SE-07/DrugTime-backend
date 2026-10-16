from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from drugtime.modules.family.adapters.inbound.schemas import (
    ErrorDetail,
    FamilyLinkApproval,
    FamilyLinkApprovalRequest,
    FamilyLinkConsentConfirmation,
    FamilyLinkRejection,
    LinkCode,
    PendingFamilyLink,
    PendingFamilyLinkList,
)
from drugtime.modules.family.adapters.outbound.module_gateways import (
    DisplayNamesGateway,
    SharingConsentGateway,
)
from drugtime.modules.family.adapters.outbound.sql_confirmations import SqlConfirmations
from drugtime.modules.family.adapters.outbound.sql_link_audit import SqlLinkAudit
from drugtime.modules.family.adapters.outbound.sql_link_codes import SqlLinkCodes
from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.application.get_link_code import get_link_code
from drugtime.modules.family.application.list_pending_links import list_pending_links
from drugtime.modules.family.application.manage_links import approve_link, reject_link
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, get_uow, unit_of_work
from drugtime.shared.errors import ServiceUnavailable

router = APIRouter(prefix="/family", tags=["family"])

# TODO(3.13): POST /family/link-requests (dùng mã; yêu cầu consent family_sharing của patient qua
#       consent.api). TODO: PATCH /family/links/{id}/sharing, DELETE /family/links/{id}.


# Mã liên kết của chính người gọi, không phải dữ liệu sức khỏe: không qua PEP, không ghi
# access_logs. Không log mã (bí mật cấp quyền gửi yêu cầu liên kết).
@router.get(
    "/link-code",
    response_model=LinkCode,
    responses={
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        403: {"model": ErrorDetail, "description": "khong_co_quyen: tài khoản admin"},
        503: {"model": ErrorDetail, "description": "link_code_unavailable"},
    },
    operation_id="getMyLinkCode",
)
def get_my_link_code(
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> LinkCode:
    record = get_link_code(uow, user_id=user.id, is_admin=user.is_admin, codes=SqlLinkCodes())
    return LinkCode.from_record(record)


# Metadata management uses ownership checks and a dedicated append-only audit.
# Health data routes continue to use access.authorize; pending links need no health consent.
def get_link_uow() -> Iterator[SqlUnitOfWork]:
    try:
        with unit_of_work() as uow:
            yield uow
    except SQLAlchemyError as exc:
        # Includes commit failures. Function scope guarantees commit before sending 200.
        raise ServiceUnavailable("service_unavailable") from exc


LinkUow = Annotated[SqlUnitOfWork, Depends(get_link_uow, scope="function")]


def link_user(uow: LinkUow, authorization: str | None = Header(None)) -> identity.CurrentUser:
    # Reuse identity's public authentication in the same guarded transaction.
    return identity.current_user(authorization=authorization, uow=uow)


LinkUser = Annotated[identity.CurrentUser, Depends(link_user)]
LinkId = Annotated[int, Path(ge=1, le=9223372036854775807, json_schema_extra={"format": "int64"})]


async def validate_link_input(request: Request) -> None:
    errors = []
    queries = list(request.query_params.multi_items())
    if request.method == "GET":
        for key, value in queries:
            if key != "status":
                errors.append({"type": "extra_forbidden", "loc": ("query", key), "input": value})
        if len(request.query_params.getlist("status")) > 1:
            errors.append(
                {
                    "type": "value_error",
                    "loc": ("query", "status"),
                    "input": None,
                    "msg": "status must occur exactly once",
                }
            )
    elif queries:
        errors.extend(
            {"type": "extra_forbidden", "loc": ("query", key), "input": value}
            for key, value in queries
        )
    if request.method == "GET" or request.url.path.endswith("/reject"):
        if await request.body():
            errors.append({"type": "extra_forbidden", "loc": ("body",), "input": None})
    if errors:
        raise RequestValidationError(errors)


_LINK_ERRORS = {
    401: {"model": ErrorDetail},
    403: {"model": ErrorDetail},
    503: {"model": ErrorDetail},
}
_DECISION_ERRORS = {**_LINK_ERRORS, 404: {"model": ErrorDetail}, 409: {"model": ErrorDetail}}


@router.get(
    "/links",
    response_model=PendingFamilyLinkList,
    operation_id="listPendingFamilyLinks",
    responses=_LINK_ERRORS,
)
def pending_family_links(
    user: LinkUser,
    uow: LinkUow,
    status: Annotated[Literal["pending"], Query()],
    validated: Annotated[None, Depends(validate_link_input)],
) -> PendingFamilyLinkList:
    records = list_pending_links(
        uow,
        actor_id=user.id,
        is_admin=user.is_admin,
        links=SqlLinks(),
        names=DisplayNamesGateway(),
        audit=SqlLinkAudit(),
    )
    return PendingFamilyLinkList(
        items=[
            PendingFamilyLink(
                link_id=r.link_id,
                family_user_id=r.family_user_id,
                family_full_name=r.family_full_name,
                status="pending",
                requested_at=r.requested_at,
            )
            for r in records
        ]
    )


@router.post(
    "/links/{link_id}/approve",
    response_model=FamilyLinkApproval,
    operation_id="approveFamilyLink",
    responses={
        **_DECISION_ERRORS,
        422: {
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/HTTPValidationError"},
                            {"$ref": "#/components/schemas/ErrorDetail"},
                        ]
                    }
                }
            }
        },
    },
)
def approve_family_link(
    link_id: LinkId,
    body: FamilyLinkApprovalRequest,
    user: LinkUser,
    uow: LinkUow,
    validated: Annotated[None, Depends(validate_link_input)],
) -> FamilyLinkApproval:
    result = approve_link(
        uow,
        link_id=link_id,
        actor_id=user.id,
        is_admin=user.is_admin,
        family_user_id=body.family_user_id,
        consent_confirmed=body.consent_confirmed,
        document_version=body.document_version,
        links=SqlLinks(),
        confirmations=SqlConfirmations(),
        consent=SharingConsentGateway(),
        audit=SqlLinkAudit(),
    )
    evidence = result.confirmation
    return FamilyLinkApproval(
        link_id=result.link.id,
        family_user_id=result.link.family_user_id,
        status="active",
        sharing_enabled=result.link.sharing_enabled,
        consent_confirmation=FamilyLinkConsentConfirmation(
            id=evidence.id,
            purpose=evidence.purpose,
            document_version=evidence.document_version,
            confirmed_at=evidence.confirmed_at,
        ),
    )


@router.post(
    "/links/{link_id}/reject",
    response_model=FamilyLinkRejection,
    operation_id="rejectFamilyLink",
    responses=_DECISION_ERRORS,
)
def reject_family_link(
    link_id: LinkId,
    user: LinkUser,
    uow: LinkUow,
    validated: Annotated[None, Depends(validate_link_input)],
) -> FamilyLinkRejection:
    link = reject_link(
        uow,
        link_id=link_id,
        actor_id=user.id,
        is_admin=user.is_admin,
        links=SqlLinks(),
        confirmations=SqlConfirmations(),
        audit=SqlLinkAudit(),
    )
    return FamilyLinkRejection(
        link_id=link.id,
        family_user_id=link.family_user_id,
        status="rejected",
        rejected_at=link.rejected_at,
    )
