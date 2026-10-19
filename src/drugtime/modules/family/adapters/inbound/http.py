from datetime import timedelta

from fastapi import APIRouter, Depends, Response

from drugtime.modules.family.adapters.inbound.schemas import (
    ErrorDetail,
    LinkCode,
    LinkRequest,
    LinkRequestCreate,
)
from drugtime.modules.family.adapters.outbound.consents import ConsentAdapter
from drugtime.modules.family.adapters.outbound.sql_link_attempts import SqlLinkAttempts
from drugtime.modules.family.adapters.outbound.sql_link_codes import SqlLinkCodes
from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.application.get_link_code import get_link_code
from drugtime.modules.family.application.send_link_request import (
    LinkRequestCommand,
    send_link_request,
)
from drugtime.modules.family.domain.link_request import LinkRequestLimits
from drugtime.modules.identity import api as identity
from drugtime.shared import clock
from drugtime.shared.config import get_settings
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(prefix="/family", tags=["family"])

# TODO: PATCH /family/links/{id}/sharing, DELETE /family/links/{id}.


# Mã liên kết của chính người gọi, không phải dữ liệu sức khỏe: không qua PEP, không ghi
# access_logs. Không log mã (bí mật cấp quyền gửi yêu cầu liên kết).
@router.get(
    "/link-code",
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
    "/link-requests",
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
