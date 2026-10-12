"""Router 7: Caregiver & Family Linking with Rate-Limiting, Multi-use Code & Admin Emergency Override (Schema v9)."""
import random
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request, Header, status, HTTPException
from app.schemas.common import ResponseEnvelope, MessageResponse, PaginatedData, PaginationMeta
from app.schemas.caregivers import (
    LinkCodeResponse, RedeemLinkCodeRequest, CaregiverLinkResponse,
    CaregiverLinkUpdateRequest, MonitoredPatientResponse, NotificationResponse
)
from app.core.security import CurrentUser, get_current_user
from app.core.rate_limit import redeem_rate_limiter, code_failure_tracker, get_client_ip
from app.mock_db import db, current_time_iso
from app.core.access_control import log_access

router = APIRouter(prefix="", tags=["7. Caregiver & Family Linking"])

@router.post(
    "/caregivers/link-codes",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[LinkCodeResponse],
    summary="Bệnh nhân sinh mã 6 số / QR mời người thân (hạn 15 phút, Multi-use)",
    description="Tạo mã liên kết tạm thời. Mã có tính chất Multi-use trong suốt 15 phút. Tự động hủy các mã active trước đó của bệnh nhân."
)
def create_link_code(caller: CurrentUser = Depends(get_current_user)):
    user = db.users.get(caller.user_id)
    patient_name = user.get("full_name", user.get("ho_ten", "Bệnh nhân")) if user else "Bệnh nhân"
    
    # Invalidate any previously active link codes for this patient
    for c in db.link_codes:
        if c.get("patient_user_id") == caller.user_id and c.get("status", c.get("trang_thai")) == "active":
            c["status"] = "expired"
            c["trang_thai"] = "expired"

    # Generate 6-char code
    code = f"DT-{random.randint(1000, 9999)}"
    now_dt = datetime.now(timezone.utc)
    expires_at = (now_dt + timedelta(minutes=15)).isoformat()
    
    record = {
        "id": len(db.link_codes) + 1,
        "patient_user_id": caller.user_id,
        "code": code,
        "ma": code,
        "expires_at": expires_at,
        "het_han_luc": expires_at,
        "status": "active",
        "trang_thai": "active",
        "is_used": False,
        "da_dung": False,
        "family_user_id": None
    }
    db.link_codes.append(record)
    
    return ResponseEnvelope(
        data=LinkCodeResponse(code=code, expires_at=record["expires_at"], patient_name=patient_name),
        message="Đã tạo mã mời liên kết thành công. Mã có hiệu lực trong 15 phút (cho phép nhiều người thân cùng kết nối)."
    )

@router.post(
    "/caregivers/link-codes/redeem",
    response_model=ResponseEnvelope[CaregiverLinkResponse],
    summary="Người thân nhập mã liên kết (Rate-Limit kép & Multi-use 15 phút)",
    description="Kiểm tra mã liên kết và tạo liên kết caregiver. Bị khóa sau 5 lần thử sai / 15p và tự động hủy mã nếu bị dò sai > 10 lần toàn cục."
)
def redeem_link_code(
    req: RedeemLinkCodeRequest,
    request: Request,
    caller: CurrentUser = Depends(get_current_user)
):
    ip = get_client_ip(request)
    rate_limit_key = f"{caller.user_id}:{ip}"
    code_input = req.code.strip().upper()
    
    # 1. Check code-level brute force lock
    code_failure_tracker.check(code_input)

    # 2. Check caller-level rate limit
    redeem_rate_limiter.check(rate_limit_key)

    # 3. Check code validity
    link_code = next((
        c for c in db.link_codes
        if c.get("code", c.get("ma", "")).strip().upper() == code_input
        and c.get("status", c.get("trang_thai", "active")) == "active"
    ), None)

    if not link_code:
        redeem_rate_limiter.record_failure(rate_limit_key)
        fails = code_failure_tracker.record_failure(code_input)
        if fails >= 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LINK_CODE_INVALIDATED",
                    "message": "Mã liên kết này đã bị vô hiệu hóa do nhập sai quá 10 lần trên toàn hệ thống. Vui lòng yêu cầu bệnh nhân sinh mã mới."
                }
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_LINK_CODE",
                "message": "Mã liên kết không hợp lệ hoặc đã hết hạn sử dụng. Vui lòng kiểm tra lại."
            }
        )

    if link_code["patient_user_id"] == caller.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "CANNOT_LINK_SELF", "message": "Bạn không thể tự liên kết làm người thân của chính mình."}
        )

    # Check if already linked
    existing = next((
        l for l in db.caregiver_links
        if l["patient_user_id"] == link_code["patient_user_id"]
        and l["family_user_id"] == caller.user_id
        and l.get("status", l.get("trang_thai")) == "active"
    ), None)
    if existing:
        return ResponseEnvelope(
            data=CaregiverLinkResponse(
                id=existing["id"],
                patient_user_id=existing["patient_user_id"],
                patient_name=existing.get("patient_name"),
                family_user_id=existing["family_user_id"],
                family_name=existing.get("family_name"),
                status=existing.get("status", existing.get("trang_thai")),
                sharing_enabled=existing.get("sharing_enabled", existing.get("cho_phep_chia_se", True)),
                linked_at=existing.get("linked_at", existing.get("thoi_gian_lien_ket")),
                revoked_at=existing.get("revoked_at", existing.get("thoi_gian_thu_hoi"))
            ),
            message="Bạn đã liên kết với bệnh nhân này từ trước."
        )

    # Success: Reset rate limiter for this key
    redeem_rate_limiter.reset(rate_limit_key)
    patient = db.users.get(link_code["patient_user_id"], {})
    link_id = len(db.caregiver_links) + 1
    new_link = {
        "id": link_id,
        "patient_user_id": link_code["patient_user_id"],
        "patient_name": patient.get("full_name", patient.get("ho_ten", "Bệnh nhân")),
        "family_user_id": caller.user_id,
        "family_name": caller.full_name or caller.ho_ten,
        "status": "active",
        "trang_thai": "active",
        "sharing_enabled": True,
        "cho_phep_chia_se": True,
        "cho_phep_chinh_sua": True, # support both for testing
        "linked_at": current_time_iso(),
        "thoi_gian_lien_ket": current_time_iso(),
        "revoked_at": None,
        "thoi_gian_thu_hoi": None
    }
    db.caregiver_links.append(new_link)

    return ResponseEnvelope(
        data=CaregiverLinkResponse(
            id=new_link["id"],
            patient_user_id=new_link["patient_user_id"],
            patient_name=new_link["patient_name"],
            family_user_id=new_link["family_user_id"],
            family_name=new_link["family_name"],
            status=new_link["status"],
            sharing_enabled=new_link["sharing_enabled"],
            linked_at=new_link["linked_at"],
            revoked_at=new_link["revoked_at"]
        ),
        message=f"Liên kết thành công với bệnh nhân {new_link['patient_name']}. Bạn đang có quyền xem lịch uống thuốc."
    )

@router.get(
    "/caregivers/my-caregivers",
    response_model=ResponseEnvelope[List[CaregiverLinkResponse]],
    summary="Bệnh nhân xem danh sách người thân đang liên kết",
    description="Hiển thị danh sách người thân kèm công tắc cho phép chia sẻ dữ liệu (sharing_enabled)."
)
def get_my_caregivers(caller: CurrentUser = Depends(get_current_user)):
    links = [
        l for l in db.caregiver_links
        if l["patient_user_id"] == caller.user_id and l.get("status", l.get("trang_thai")) != "revoked"
    ]
    formatted = [
        CaregiverLinkResponse(
            id=l["id"],
            patient_user_id=l["patient_user_id"],
            patient_name=l.get("patient_name"),
            family_user_id=l["family_user_id"],
            family_name=l.get("family_name"),
            status=l.get("status", l.get("trang_thai")),
            sharing_enabled=l.get("sharing_enabled", l.get("cho_phep_chia_se", True)),
            linked_at=l.get("linked_at", l.get("thoi_gian_lien_ket")),
            revoked_at=l.get("revoked_at", l.get("thoi_gian_thu_hoi"))
        )
        for l in links
    ]
    return ResponseEnvelope(data=formatted)

@router.patch(
    "/caregivers/{link_id}",
    response_model=ResponseEnvelope[CaregiverLinkResponse],
    summary="Cập nhật quyền hoặc thu hồi liên kết (Hỗ trợ Admin Emergency Override)",
    description="Cho phép bệnh nhân cập nhật quyền chia sẻ hoặc Admin thực hiện can thiệp khẩn cấp (chỉ được thu hồi, bắt buộc X-Admin-Reason, sinh Four-Eyes hậu kiểm 24h)."
)
def update_caregiver_link(
    link_id: int,
    req: CaregiverLinkUpdateRequest,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    link = next((l for l in db.caregiver_links if l["id"] == link_id), None)
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "CAREGIVER_LINK_NOT_FOUND", "message": "Không tìm thấy liên kết người thân"})

    # Case 1: Admin Emergency Override
    if caller.system_role == "admin":
        from urllib.parse import unquote
        decoded_reason = unquote(x_admin_reason) if x_admin_reason else None
        if not decoded_reason or len(decoded_reason.strip()) < 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "ADMIN_OVERRIDE_REASON_REQUIRED",
                    "message": "Thao tác can thiệp của Quản trị viên bắt buộc phải cung cấp lý do qua header 'X-Admin-Reason' (tối thiểu 10 ký tự)."
                }
            )

        # Admin CANNOT expand permissions or restore active link
        if req.sharing_enabled is True or req.status == "active" or req.can_edit is True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "CANNOT_EXPAND_PERMISSIONS_AS_ADMIN",
                    "message": "Quản trị viên chỉ được phép thu hẹp hoặc thu hồi liên kết người thân để bảo vệ bệnh nhân, không được phép mở rộng quyền."
                }
            )

        # Apply restrictions
        if req.sharing_enabled is False:
            link["sharing_enabled"] = False
            link["cho_phep_chia_se"] = False
            link["cho_phep_chinh_sua"] = False
        if req.status == "revoked":
            link["status"] = "revoked"
            link["trang_thai"] = "revoked"
            link["revoked_at"] = current_time_iso()
            link["thoi_gian_thu_hoi"] = current_time_iso()

        # Emergency override audit trail & 24h Four-Eyes deadline
        now_dt = datetime.now(timezone.utc)
        deadline = (now_dt + timedelta(hours=24)).isoformat()
        audit_entry = {
            "id": len(db.access_logs) + 1,
            "actor_user_id": caller.user_id,
            "actor_role": "admin",
            "patient_user_id": link["patient_user_id"],
            "data_scope": "ho_so_suc_khoe",
            "action": "REVOKE_CAREGIVER",
            "result": "allowed",
            "override_reason": decoded_reason,
            "is_emergency_override": True,
            "review_status": "pending_post_review",
            "review_deadline": deadline,
            "compliance_flags": [],
            "accessed_at": current_time_iso(),
            # Compatibility aliases
            "ket_qua": "allowed",
            "ly_do_can_thiep": decoded_reason,
            "thoi_gian": current_time_iso()
        }
        db.access_logs.append(audit_entry)

        # Send automatic in-app notification to patient
        caregiver_name = link.get("family_name") or "Người thân"
        db.notifications.append({
            "id": len(db.notifications) + 1,
            "user_id": link["patient_user_id"],
            "about_patient_user_id": link["patient_user_id"],
            "type": "canh_bao_admin_override",
            "content": f"Quản trị viên đã thực hiện thu hồi liên kết người thân {caregiver_name} vì lý do: {decoded_reason}.",
            "is_read": False,
            "dedupe_key": None,
            "created_at": current_time_iso(),
            # Compatibility
            "ve_patient_user_id": link["patient_user_id"],
            "loai": "canh_bao_admin_override",
            "noi_dung": f"Quản trị viên đã thực hiện thu hồi liên kết người thân {caregiver_name} vì lý do: {decoded_reason}.",
            "da_doc": False,
            "thoi_gian": current_time_iso()
        })

        return ResponseEnvelope(
            data=CaregiverLinkResponse(
                id=link["id"],
                patient_user_id=link["patient_user_id"],
                patient_name=link.get("patient_name"),
                family_user_id=link["family_user_id"],
                family_name=link.get("family_name"),
                status=link.get("status", link.get("trang_thai")),
                sharing_enabled=link.get("sharing_enabled", link.get("cho_phep_chia_se", True)),
                linked_at=link.get("linked_at", link.get("thoi_gian_lien_ket")),
                revoked_at=link.get("revoked_at", link.get("thoi_gian_thu_hoi"))
            ),
            message="Đã thực hiện can thiệp khẩn cấp thu hồi liên kết người thân. Thao tác đang chờ hậu kiểm Four-Eyes trong 24h."
        )

    # Case 2: Self (Patient)
    if link["patient_user_id"] != caller.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "Bạn không có quyền chỉnh sửa liên kết này"})

    if req.sharing_enabled is not None:
        link["sharing_enabled"] = req.sharing_enabled
        link["cho_phep_chia_se"] = req.sharing_enabled
    if req.status is not None:
        link["status"] = req.status
        link["trang_thai"] = req.status
        if req.status == "revoked":
            link["revoked_at"] = current_time_iso()
            link["thoi_gian_thu_hoi"] = current_time_iso()

    return ResponseEnvelope(
        data=CaregiverLinkResponse(
            id=link["id"],
            patient_user_id=link["patient_user_id"],
            patient_name=link.get("patient_name"),
            family_user_id=link["family_user_id"],
            family_name=link.get("family_name"),
            status=link.get("status", link.get("trang_thai")),
            sharing_enabled=link.get("sharing_enabled", link.get("cho_phep_chia_se", True)),
            linked_at=link.get("linked_at", link.get("thoi_gian_lien_ket")),
            revoked_at=link.get("revoked_at", link.get("thoi_gian_thu_hoi"))
        ),
        message="Đã cập nhật quyền người thân thành công"
    )

@router.get(
    "/caregivers/monitored-patients",
    response_model=ResponseEnvelope[List[MonitoredPatientResponse]],
    summary="Người thân lấy danh sách bệnh nhân đang giám sát (Multi-Patient Switcher)",
    description="Dùng để hiển thị menu chuyển đổi bệnh nhân trên Mobile kèm tỷ lệ tuân thủ hôm nay."
)
def get_monitored_patients(caller: CurrentUser = Depends(get_current_user)):
    links = [
        l for l in db.caregiver_links
        if l["family_user_id"] == caller.user_id and l.get("status", l.get("trang_thai")) == "active"
    ]
    results = []
    for l in links:
        p = db.users.get(l["patient_user_id"], {})
        results.append(MonitoredPatientResponse(
            patient_id=l["patient_user_id"],
            full_name=p.get("full_name", p.get("ho_ten", "Bệnh nhân")),
            link_id=l["id"],
            sharing_enabled=l.get("sharing_enabled", l.get("cho_phep_chia_se", True)),
            today_adherence_percent=85.5,
            today_missed_count=0
        ))
    return ResponseEnvelope(data=results)

@router.get(
    "/notifications",
    response_model=ResponseEnvelope[PaginatedData[NotificationResponse]],
    summary="Lấy thông báo của tài khoản (nhắc thuốc, cảnh báo người thân)",
    description="Lấy danh sách thông báo gửi đến người dùng (Schema v9: dedupe_key, created_at)."
)
def get_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    caller: CurrentUser = Depends(get_current_user)
):
    user_notifs = [n for n in db.notifications if n["user_id"] == caller.user_id]
    if not user_notifs:
        user_notifs = [
            {
                "id": 1,
                "user_id": caller.user_id,
                "about_patient_user_id": caller.user_id,
                "type": "nhac_uong_thuoc",
                "content": "Đến giờ uống Glucophage 500mg (1 viên).",
                "is_read": False,
                "dedupe_key": None,
                "created_at": current_time_iso()
            }
        ]
    total = len(user_notifs)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = [
        NotificationResponse(
            id=n["id"],
            user_id=n["user_id"],
            about_patient_user_id=n.get("about_patient_user_id", n.get("ve_patient_user_id")),
            type=n.get("type", n.get("loai")),
            content=n.get("content", n.get("noi_dung")),
            is_read=n.get("is_read", n.get("da_doc", False)),
            dedupe_key=n.get("dedupe_key"),
            created_at=n.get("created_at", n.get("thoi_gian", current_time_iso()))
        )
        for n in user_notifs[start:start+page_size]
    ]
    return ResponseEnvelope(
        data=PaginatedData(
            items=paged,
            pagination=PaginationMeta(page=page, page_size=page_size, total_items=total, total_pages=pages)
        )
    )

@router.patch(
    "/notifications/{id}/read",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Đánh dấu đã đọc thông báo",
    description="Đánh dấu thông báo đã được xem."
)
def mark_notification_read(id: int, caller: CurrentUser = Depends(get_current_user)):
    notif = next((n for n in db.notifications if n["id"] == id and n["user_id"] == caller.user_id), None)
    if notif:
        notif["is_read"] = True
        notif["da_doc"] = True
    return ResponseEnvelope(data=MessageResponse(message=f"Đã đánh dấu đọc thông báo #{id}."))
