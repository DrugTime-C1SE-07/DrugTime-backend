"""Router 2: Consents & Data Privacy (Schema v9: ND 356/2025/ND-CP, QA.01, CD9)."""
from typing import List
from fastapi import APIRouter, Depends, status
from app.schemas.common import ResponseEnvelope
from app.schemas.consents import (
    ConsentStatusResponse, SubmitConsentRequest, ConsentRecordResponse,
    DataDeletionRequestCreate, DataDeletionRequestResponse
)
from app.core.security import CurrentUser, get_current_user
from app.mock_db import db, current_time_iso

router = APIRouter(prefix="", tags=["2. Consent & Privacy"])

@router.get(
    "/consents/me",
    response_model=ResponseEnvelope[List[ConsentStatusResponse]],
    summary="Lấy trạng thái các mục đích đồng thuận của người dùng",
    description="Tuân thủ NĐ 356/2025 & QA.01: Trả về trạng thái của 3 mục đích tách rời: health_data, family_sharing, ai_meal."
)
def get_my_consents(caller: CurrentUser = Depends(get_current_user)):
    purposes = ["health_data", "family_sharing", "ai_meal"]
    results = []
    
    for purpose in purposes:
        # Get latest consent record
        matching = [
            c for c in db.user_consents
            if c["user_id"] == caller.user_id and c.get("consent_type", c.get("loai_dong_y")) == purpose
        ]
        if matching:
            latest = matching[-1]
            results.append(ConsentStatusResponse(
                consent_type=latest.get("consent_type", latest.get("loai_dong_y")),
                status=latest.get("status", latest.get("trang_thai")),
                consented_at=latest.get("consented_at", latest.get("thoi_gian_dong_y")),
                revoked_at=latest.get("revoked_at", latest.get("thoi_gian_thu_hoi")),
                document_version=latest.get("document_version", latest.get("phien_ban_van_ban", "v1.0"))
            ))
        else:
            results.append(ConsentStatusResponse(
                consent_type=purpose, # type: ignore
                status="thu_hoi",
                consented_at=None,
                revoked_at=None,
                document_version="v1.0"
            ))
            
    return ResponseEnvelope(data=results)

@router.post(
    "/consents",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[ConsentRecordResponse],
    summary="Cấp mới hoặc thu hồi đồng thuận xử lý dữ liệu (QA.01)",
    description="Lưu theo cơ chế Append-only. Rút consent có hiệu lực ngay ở request kế tiếp mà không qua hàng đợi xóa dữ liệu."
)
def submit_consent(req: SubmitConsentRequest, caller: CurrentUser = Depends(get_current_user)):
    now = current_time_iso()
    
    record = {
        "id": len(db.user_consents) + 1,
        "user_id": caller.user_id,
        "consent_type": req.consent_type,
        "loai_dong_y": req.consent_type,
        "status": req.status,
        "trang_thai": req.status,
        "consented_at": now if req.status == "dong_y" else None,
        "thoi_gian_dong_y": now if req.status == "dong_y" else None,
        "revoked_at": now if req.status == "thu_hoi" else None,
        "thoi_gian_thu_hoi": now if req.status == "thu_hoi" else None,
        "document_version": req.document_version,
        "phien_ban_van_ban": req.document_version
    }
    db.user_consents.append(record)
    
    msg = f"Đã cập nhật đồng thuận {req.consent_type} sang trạng thái {req.status}"
    return ResponseEnvelope(data=ConsentRecordResponse(**record), message=msg)

@router.post(
    "/data-deletion-requests",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResponseEnvelope[DataDeletionRequestResponse],
    summary="Gửi yêu cầu xóa toàn bộ dữ liệu cá nhân (QA.01, CD9)",
    description="Gửi yêu cầu xóa dữ liệu cá nhân theo NĐ 356/2025/NĐ-CP. Chỉ dùng cho yêu cầu xóa dữ liệu (cần Admin duyệt)."
)
def request_data_deletion(req: DataDeletionRequestCreate, caller: CurrentUser = Depends(get_current_user)):
    now = current_time_iso()
    
    record = {
        "id": len(db.data_deletion_requests) + 1,
        "user_id": caller.user_id,
        "status": "cho_duyet",
        "requested_at": now,
        "handled_by_admin_id": None,
        "handled_at": None,
        "rejection_reason": None,
        "completed_at": None,
        "last_error": None
    }
    db.data_deletion_requests.append(record)
    
    return ResponseEnvelope(
        data=DataDeletionRequestResponse(**record),
        message="Yêu cầu xóa dữ liệu cá nhân đã được tiếp nhận và chuyển đến Quản trị viên phê duyệt."
    )

@router.get(
    "/data-deletion-requests/me",
    response_model=ResponseEnvelope[List[DataDeletionRequestResponse]],
    summary="Xem tiến độ các yêu cầu xóa dữ liệu cá nhân của mình",
    description="Cho phép người dùng kiểm tra trạng thái phê duyệt và thực thi của các yêu cầu xóa dữ liệu đã gửi."
)
def get_my_deletion_requests(caller: CurrentUser = Depends(get_current_user)):
    user_requests = [r for r in db.data_deletion_requests if r["user_id"] == caller.user_id]
    return ResponseEnvelope(data=[DataDeletionRequestResponse(**r) for r in user_requests])
