"""Người thân gửi yêu cầu liên kết bằng mã của người bệnh (task 3.13, QD-04, QD-34).

Thứ tự kiểm khớp mô tả `POST /family/link-requests` trong api_contract. Không log và không đưa
mã vào message lỗi: mã cấp quyền gửi yêu cầu và không đổi được (QD-04).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import NoReturn
from uuid import UUID

from drugtime.modules.family.application.ports import Consents, LinkAttempts, LinkCodes, Links
from drugtime.modules.family.domain.link import (
    FamilyLink,
    FamilyLinkError,
    ensure_can_create_link,
    pending_link,
)
from drugtime.modules.family.domain.link_request import (
    LinkRequestLimits,
    cooldown_until,
    next_vn_midnight,
    vn_day_start,
)
from drugtime.modules.family.domain.throttle import (
    ThrottleState,
    is_locked,
    on_failure,
    retry_after,
)
from drugtime.shared.errors import Forbidden, NotFound, TooManyRequests
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class LinkRequestCommand:
    client_uuid: UUID
    code: str  # đã chuẩn hóa (bỏ khoảng trắng hai đầu, chữ hoa) và đúng định dạng


def send_link_request(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    cmd: LinkRequestCommand,
    now: datetime,
    links: Links,
    codes: LinkCodes,
    attempts: LinkAttempts,
    consents: Consents,
    limits: LinkRequestLimits,
) -> tuple[FamilyLink, bool]:
    """Trả (yêu cầu, True) khi vừa tạo; (yêu cầu đã tạo trước đó, False) khi gửi lại cùng
    `client_uuid` (khi đó body lần sau bị bỏ qua)."""
    if caller_is_admin:
        # Tài khoản admin tách khỏi tài khoản cá nhân (QD-44).
        raise Forbidden("khong_co_quyen")

    # Mọi request liên kết của cùng người gửi chạy lần lượt: không vượt ngưỡng sai khi gửi
    # đồng thời, và hai request cùng client_uuid chỉ tạo một yêu cầu.
    links.lock_sender(uow, caller_id)
    existing = links.find_by_client_uuid(uow, caller_id, cmd.client_uuid)
    if existing is not None:
        return existing, False

    state = attempts.state(uow, caller_id, cmd.client_uuid, now, limits)
    if is_locked(state, now):
        raise TooManyRequests("link_request_locked", retry_after(state.locked_until, now))
    if links.count_created_since(uow, caller_id, vn_day_start(now)) >= limits.daily_request_limit:
        raise TooManyRequests("link_request_daily_limit", retry_after(next_vn_midnight(now), now))

    owner = codes.find_owner(uow, cmd.code)
    if owner is None:
        _fail(attempts, caller_id, cmd.client_uuid, state, now, limits)
    if owner == caller_id:
        raise FamilyLinkError("self_link_not_allowed", "link code belongs to the caller")
    if not consents.has_family_sharing(uow, owner):
        # BS-05: trả giống hệt mã không tồn tại, không lộ trạng thái consent (QD-34 (b)).
        _fail(attempts, caller_id, cmd.client_uuid, state, now, limits)

    ensure_can_create_link(owner, caller_id, links.find_open_by_pair(uow, owner, caller_id))
    streak, last_rejected_at = links.rejection_streak(uow, owner, caller_id)
    blocked_until = cooldown_until(streak, last_rejected_at, limits)
    if blocked_until is not None and now < blocked_until:
        raise TooManyRequests("link_request_cooldown", retry_after(blocked_until, now))

    link = replace(pending_link(owner, caller_id), client_uuid=cmd.client_uuid)
    return links.create(uow, link), True


def _fail(
    attempts: LinkAttempts,
    caller_id: UUID,
    client_uuid: UUID,
    state: ThrottleState,
    now: datetime,
    limits: LinkRequestLimits,
) -> NoReturn:
    """Một lần nhập sai: ghi ở transaction riêng rồi trả 404. Một `client_uuid` chỉ tính
    một lần (app tự gửi lại khi mất mạng không làm tăng số lần sai)."""
    if not state.client_uuid_failed:
        attempts.record_failure(caller_id, client_uuid, now, on_failure(state, now, limits))
    raise NotFound("link_code_not_found")
