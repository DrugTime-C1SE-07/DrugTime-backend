from datetime import UTC, datetime
from fastapi import APIRouter, Depends, Response, status

from drugtime.modules.family.adapters.inbound.schemas import ErrorDetail, LinkCode
from drugtime.modules.family.adapters.outbound.sql_link_codes import SqlLinkCodes
from drugtime.modules.family.adapters.outbound.sql_links import SqlLinks
from drugtime.modules.family.application import manage_links
from drugtime.modules.family.application.get_link_code import get_link_code
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(tags=["family"])

# TODO(3.13): POST /family/link-requests (dùng mã; yêu cầu consent family_sharing của patient qua
#       consent.api). TODO: PATCH /family/links/{id}/sharing.


# Mã liên kết của chính người gọi, không phải dữ liệu sức khỏe: không qua PEP, không ghi
# access_logs. Không log mã (bí mật cấp quyền gửi yêu cầu liên kết).
@router.get(
    "/family/link-code",
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


@router.delete(
    "/links/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Thu hồi hoặc tự rời liên kết thành công, hoặc đã thu hồi từ trước"},
        401: {"model": ErrorDetail, "description": "Chưa xác thực hoặc token không hợp lệ"},
        403: {"model": ErrorDetail, "description": "khong_co_quyen: link không tồn tại hoặc không thuộc người gọi"},
    },
    operation_id="revokeLink",
)
def delete_link(
    id: int,
    uow: SqlUnitOfWork = Depends(get_uow),
    user: identity.CurrentUser = Depends(identity.current_user),
) -> Response:
    manage_links.revoke_link(
        uow,
        link_id=id,
        caller_id=user.id,
        now=datetime.now(UTC),
        links=SqlLinks(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

