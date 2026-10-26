from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from drugtime.modules.family.adapters.inbound.schemas import (
    Caregiver,
    CaregiverList,
    ErrorDetail,
    FamilyLinkApproval,
    FamilyLinkApprovalRequest,
    FamilyLinkConsentConfirmation,
    FamilyLinkRejection,
    FamilyLinkRevocation,
    FamilyLinkSharingUpdate,
    LinkCode,
    LinkRequest,
    LinkRequestCreate,
    PendingFamilyLink,
    PendingFamilyLinkList,
)
from drugtime.modules.family.adapters.outbound.consents import ConsentAdapter
from drugtime.modules.family.adapters.outbound.module_gateways import (
    DisplayNamesGateway,
    SharingConsentGateway,
)
from drugtime.modules.family.adapters.outbound.sql_confirmations import SqlConfirmations
from drugtime.modules.family.adapters.outbound.sql_link_attempts import SqlLinkAttempts
from drugtime.modules.family.adapters.outbound.sql_link_audit import SqlLinkAudit
from drugtime.modules.family.adapters.outbound.sql_link_codes import SqlLinkCodes
from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.application import manage_links
from drugtime.modules.family.application.get_link_code import get_link_code
from drugtime.modules.family.application.list_caregivers import list_caregivers
from drugtime.modules.family.application.list_pending_links import list_pending_links
from drugtime.modules.family.application.manage_links import (
    approve_link,
    reject_link,
    revoke_link,
    update_sharing,
)
from drugtime.modules.family.application.send_link_request import (
    LinkRequestCommand,
    send_link_request,
)
from drugtime.modules.family.domain.consent_confirmation import Caregiver as CaregiverRecord
from drugtime.modules.family.domain.link_request import LinkRequestLimits
from drugtime.modules.identity import api as identity
from drugtime.shared import clock
from drugtime.shared.config import get_settings
from drugtime.shared.db import SqlUnitOfWork, get_uow, unit_of_work
from drugtime.shared.errors import ServiceUnavailable

router = APIRouter(tags=["family"])


# Mã liên kết của chính người gọi, không phải dữ liệu sức khỏe: không qua PEP, không ghi
# access_logs. Không log mã (bí mật cấp quyền gửi yêu cầu liên kết).
@router.get(
    "/family/link-code",
    response_model=LinkCode,
    responses={
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        403: {
            "model": ErrorDetail,
            "description": "khong_co_quyen: tài khoản admin | family_sharing_consent_required: "
            "người gọi chưa đồng ý (hoặc đã rút) family_sharing",
        },
        503: {"model": ErrorDetail, "description": "link_code_unavailable"},
    },
    operation_id="getMyLinkCode",
)
def get_my_link_code(
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> LinkCode:
    record = get_link_code(
        uow,
        user_id=user.id,
        is_admin=user.is_admin,
        codes=SqlLinkCodes(),
        consents=ConsentAdapter(),
    )
    return LinkCode.from_record(record)


def _limits() -> LinkRequestLimits:
    s = get_settings()
    return LinkRequestLimits(
        fail_window=timedelta(minutes=s.link_fail_window_minutes),
        fail_account_limit=s.link_fail_account_limit,
        lock_duration=timedelta(minutes=s.link_lock_minutes),
        daily_request_limit=s.link_daily_request_limit,
        reject_streak_limit=s.link_reject_streak_limit,
        reject_cooldown=timedelta(hours=s.link_reject_cooldown_hours),
    )


# Không chạm dữ liệu sức khỏe: không qua PEP, không ghi access_logs. Không log mã.
@router.post(
    "/family/link-requests",
    status_code=201,
    response_model=LinkRequest,
    responses={
        200: {"model": LinkRequest, "description": "Gửi lại với client_uuid đã thành công"},
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        403: {"model": ErrorDetail, "description": "khong_co_quyen: tài khoản admin"},
        404: {"model": ErrorDetail, "description": "link_code_not_found"},
        409: {"model": ErrorDetail, "description": "link_request_pending | already_linked"},
        422: {"description": "ValidationError, hoặc ErrorDetail với self_link_not_allowed"},
        429: {
            "model": ErrorDetail,
            "description": "link_request_locked | link_request_daily_limit | link_request_cooldown",
            "headers": {
                "Retry-After": {
                    "description": "Số giây còn phải chờ",
                    "schema": {"type": "integer", "minimum": 1},
                }
            },
        },
    },
    operation_id="createLinkRequest",
)
def post_link_request(
    body: LinkRequestCreate,
    response: Response,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> LinkRequest:
    link, created = send_link_request(
        uow,
        caller_id=user.id,
        caller_is_admin=user.is_admin,
        cmd=LinkRequestCommand(client_uuid=body.client_uuid, code=body.code),
        now=clock.now(),
        links=SqlLinks(),
        codes=SqlLinkCodes(),
        attempts=SqlLinkAttempts(),
        consents=ConsentAdapter(),
        limits=_limits(),
    )
    response.status_code = 201 if created else 200
    return LinkRequest.from_record(link)


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
    path = request.url.path
    # Chỉ danh sách yêu cầu đang chờ có query (status); mọi route khác không nhận query.
    if request.method == "GET" and path.endswith("/family/links"):
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
    if request.method == "GET" or path.endswith(("/reject", "/revoke")):
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
    "/family/links",
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
    "/family/links/{link_id}/approve",
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
    "/family/links/{link_id}/reject",
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


def _caregiver(record: CaregiverRecord) -> Caregiver:
    return Caregiver(
        link_id=record.link_id,
        family_user_id=record.family_user_id,
        family_full_name=record.family_full_name,
        status="active",
        sharing_enabled=record.sharing_enabled,
        approved_at=record.approved_at,
    )


@router.get(
    "/family/caregivers",
    response_model=CaregiverList,
    operation_id="listMyCaregivers",
    # Không có tham số nên FastAPI không tự thêm 422; validate_link_input vẫn trả 422.
    responses={**_LINK_ERRORS, 422: {"description": "Validation Error"}},
)
def my_caregivers(
    user: LinkUser,
    uow: LinkUow,
    validated: Annotated[None, Depends(validate_link_input)],
) -> CaregiverList:
    records = list_caregivers(
        uow,
        actor_id=user.id,
        is_admin=user.is_admin,
        links=SqlLinks(),
        names=DisplayNamesGateway(),
        audit=SqlLinkAudit(),
    )
    return CaregiverList(items=[_caregiver(r) for r in records])


@router.patch(
    "/family/links/{link_id}/sharing",
    response_model=Caregiver,
    operation_id="updateFamilyLinkSharing",
    responses=_DECISION_ERRORS,
)
def update_family_link_sharing(
    link_id: LinkId,
    body: FamilyLinkSharingUpdate,
    user: LinkUser,
    uow: LinkUow,
    validated: Annotated[None, Depends(validate_link_input)],
) -> Caregiver:
    record = update_sharing(
        uow,
        link_id=link_id,
        actor_id=user.id,
        is_admin=user.is_admin,
        enabled=body.sharing_enabled,
        links=SqlLinks(),
        confirmations=SqlConfirmations(),
        consent=SharingConsentGateway(),
        names=DisplayNamesGateway(),
        audit=SqlLinkAudit(),
    )
    return _caregiver(record)


@router.post(
    "/family/links/{link_id}/revoke",
    response_model=FamilyLinkRevocation,
    operation_id="revokeFamilyLink",
    responses=_DECISION_ERRORS,
)
def revoke_family_link(
    link_id: LinkId,
    user: LinkUser,
    uow: LinkUow,
    validated: Annotated[None, Depends(validate_link_input)],
) -> FamilyLinkRevocation:
    link = revoke_link(
        uow,
        link_id=link_id,
        actor_id=user.id,
        is_admin=user.is_admin,
        links=SqlLinks(),
        confirmations=SqlConfirmations(),
        audit=SqlLinkAudit(),
    )
    return FamilyLinkRevocation(
        link_id=link.id,
        family_user_id=link.family_user_id,
        status="revoked",
        revoked_at=link.revoked_at,
    )


@router.delete(
    "/links/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {
            "description": "Thu hồi hoặc tự rời liên kết thành công, hoặc đã thu hồi từ trước",
        },
        401: {"model": ErrorDetail, "description": "Chưa xác thực hoặc token không hợp lệ"},
        403: {
            "model": ErrorDetail,
            "description": "khong_co_quyen: link không tồn tại hoặc không thuộc người gọi",
        },
        422: {
            "model": ErrorDetail,
            "description": "invalid_link_transition: link đã bị từ chối (rejected)",
        },
    },
    operation_id="revokeLink",
)
def delete_link(
    id: int,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> Response:
    manage_links.revoke_link_as_member(
        uow,
        link_id=id,
        caller_id=user.id,
        now=datetime.now(UTC),
        links=SqlLinks(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
