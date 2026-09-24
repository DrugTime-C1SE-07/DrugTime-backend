"""Router 2: Consents & Data Privacy (ND 356/2025/ND-CP)."""
from typing import List
from fastapi import APIRouter, Depends, status
from app.schemas.common import ResponseEnvelope
from app.schemas.consents import (
    ConsentStatusResponse, SubmitConsentRequest, ConsentRecordResponse,
    DataDeletionRequestCreate, DataDeletionRequestResponse
)
from app.core.security import CurrentUser, get_current_user
from app.mock_db import db, current_time_iso
from app.core.access_control import log_access

router = APIRouter(prefix="", tags=["2. Consent & Privacy"])

@router.get(
    "/consents/me",
    response_model=ResponseEnvelope[List[ConsentStatusResponse]],
    summary="Lấy trạng thái các mục đích đồng thuận của người dùng",
    description="Tuân thủ NĐ 356/2025: Trả về trạng thái của 3 mục đích tách rời: health_data, family_sharing, ai_meal."
)
def get_my_consents(caller: CurrentUser = Depends(get_current_user)):
    log_access(caller.user_id, "self", caller.user_id, "ho_so_suc_khoe", "allowed")
    
    purposes = ["health_data", "family_sharing", "ai_meal"]
    results = []
    
    for purpose in purposes:
        # Get latest consent record
        matching = [c for c in db.user_consents if c["user_id"] == caller.user_id and c["loai_dong_y"] == purpose]
        if matching:
            latest = matching[-1]
            results.append(ConsentStatusResponse(
                loai_dong_y=latest["loai_dong_y"],
                trang_thai=latest["trang_thai"],
                thoi_gian_dong_y=latest["thoi_gian_dong_y"],
                thoi_gian_thu_hoi=latest["thoi_gian_thu_hoi"],
                phien_ban_van_ban=latest["phien_ban_van_ban"]
            ))
        else:
            results.append(ConsentStatusResponse(
                loai_dong_y=purpose, # type: ignore
                trang_thai="thu_hoi",
                thoi_gian_dong_y=None,
                thoi_gian_thu_hoi=None,
                phien_ban_van_ban="v1.0"
            ))
            
    return ResponseEnvelope(data=results)

@router.post(
    "/consents",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[ConsentRecordResponse],
    summary="Cấp mới hoặc thu hồi đồng thuận xử lý dữ liệu",
    description="Lưu theo cơ chế Append-only để giữ nguyên vết lịch sử phục vụ DPIA và kiểm toán tuân thủ."
)
def submit_consent(req: SubmitConsentRequest, caller: CurrentUser = Depends(get_current_user)):
    log_access(caller.user_id, "self", caller.user_id, "ho_so_suc_khoe", "allowed")
    now = current_time_iso()
    
    record = {
        "id": len(db.user_consents) + 1,
        "user_id": caller.user_id,
        "loai_dong_y": req.loai_dong_y,
        "trang_thai": req.trang_thai,
        "thoi_gian_dong_y": now if req.trang_thai == "dong_y" else None,
        "thoi_gian_thu_hoi": now if req.trang_thai == "thu_hoi" else None,
        "phien_ban_van_ban": req.phien_ban_van_ban
    }
    db.user_consents.append(record)
    
    msg = f"Đã cập nhật đồng thuận {req.loai_dong_y} sang trạng thái {req.trang_thai}"
    return ResponseEnvelope(data=ConsentRecordResponse(**record), message=msg)

@router.post(
    "/data-deletion-requests",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResponseEnvelope[DataDeletionRequestResponse],
    summary="Gửi yêu cầu xóa toàn bộ dữ liệu hoặc rút consent (FR09)",
    description="Gửi yêu cầu xóa dữ liệu cá nhân theo NĐ 356/2025/NĐ-CP. Yêu cầu sẽ được đưa vào hàng đợi chờ Admin phê duyệt."
)
def request_data_deletion(req: DataDeletionRequestCreate, caller: CurrentUser = Depends(get_current_user)):
    log_access(caller.user_id, "self", caller.user_id, "ho_so_suc_khoe", "allowed")
    now = current_time_iso()
    
    record = {
        "id": len(db.data_deletion_requests) + 1,
        "user_id": caller.user_id,
        "loai": req.loai,
        "loai_dong_y": req.loai_dong_y,
        "trang_thai": "cho_duyet",
        "thoi_gian_yeu_cau": now,
        "thoi_gian_xu_ly": None,
        "ly_do_tu_choi": None
    }
    db.data_deletion_requests.append(record)
    
    return ResponseEnvelope(
        data=DataDeletionRequestResponse(**record),
        message="Yêu cầu của bạn đã được tiếp nhận và chuyển đến Quản trị viên xử lý theo quy định."
    )

@router.get(
    "/data-deletion-requests/me",
    response_model=ResponseEnvelope[List[DataDeletionRequestResponse]],
    summary="Xem tiến độ các yêu cầu xóa dữ liệu cá nhân của mình",
    description="Cho phép người dùng kiểm tra trạng thái phê duyệt của các yêu cầu xóa dữ liệu đã gửi."
)
def get_my_deletion_requests(caller: CurrentUser = Depends(get_current_user)):
    user_requests = [r for r in db.data_deletion_requests if r["user_id"] == caller.user_id]
    return ResponseEnvelope(data=[DataDeletionRequestResponse(**r) for r in user_requests])
