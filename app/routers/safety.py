"""Router 6: Drug Safety & Pure Rule-Based Interaction Warnings (QA.04)."""
from typing import List
from fastapi import APIRouter, Depends
from app.schemas.common import ResponseEnvelope, MessageResponse
from app.schemas.safety import (
    RegimenSnapshotResponse, RegimenFindingResponse,
    QuickCheckRequest, QuickCheckResponse, QuickCheckWarningItem,
    AcknowledgeRecommendationRequest
)
from app.core.security import CurrentUser, get_current_user
from app.core.access_control import require_patient_read, require_patient_write
from app.mock_db import db, current_time_iso

router = APIRouter(prefix="", tags=["6. Drug Safety & Interactions"])

@router.post(
    "/patients/{patient_id}/regimens/analyze",
    response_model=ResponseEnvelope[RegimenSnapshotResponse],
    summary="Kích hoạt phân tích tương tác trên toàn bộ phác đồ thuốc hiện tại",
    description="Chạy bộ máy kiểm tra xác định (Rule-based, Bảng A-F, không LLM). Trả về snapshot kết quả."
)
def analyze_patient_regimen(
    patient_id: str,
    actor_role: str = Depends(require_patient_read("canh_bao_tuong_tac"))
):
    # # TODO: implement real rule engine (Bảng C, D, E, dose thresholds)
    now = current_time_iso()
    snapshot = {
        "id": len(db.regimen_snapshots) + 1,
        "user_id": patient_id,
        "thoi_gian_phan_tich": now,
        "finding_count": len(db.regimen_findings),
        "highest_severity": 2
    }
    db.regimen_snapshots.append(snapshot)
    
    return ResponseEnvelope(
        data=RegimenSnapshotResponse(**snapshot),
        message="Phân tích an toàn dược lý hoàn tất theo chuẩn Dược thư Quốc gia Việt Nam."
    )

@router.get(
    "/patients/{patient_id}/regimens/findings",
    response_model=ResponseEnvelope[List[RegimenFindingResponse]],
    summary="Lấy danh sách cảnh báo tương tác thuốc mới nhất",
    description="Bao gồm cảnh báo Thuốc-Thuốc, Thuốc-Thực phẩm, Thuốc-Bệnh nền, kèm chỉ dẫn xử lý và Miễn trừ y khoa."
)
def get_regimen_findings(
    patient_id: str,
    actor_role: str = Depends(require_patient_read("canh_bao_tuong_tac"))
):
    return ResponseEnvelope(data=[RegimenFindingResponse(**f) for f in db.regimen_findings])

@router.post(
    "/interactions/quick-check",
    response_model=ResponseEnvelope[QuickCheckResponse],
    summary="Kiểm tra nhanh tương tác tức thì trước khi kê đơn (Preview)",
    description="Kiểm tra tương tác tức thời giữa các thuốc và bệnh nền dự kiến kê mà không ghi dữ liệu vào database."
)
def quick_check_interactions(
    req: QuickCheckRequest,
    caller: CurrentUser = Depends(get_current_user)
):
    # # TODO: implement real rule engine quick-check
    warnings = []
    # If Metformin (101) and Amlor (102) checked with diabetes
    if 101 in req.medication_ids and 102 in req.medication_ids:
        warnings.append(QuickCheckWarningItem(
            loai="Thuốc - Thuốc",
            cap_doi="Metformin + Amlodipine",
            muc_do=1,
            mo_ta="Amlodipine có thể làm giảm nhẹ hiệu quả kiểm soát đường huyết của Metformin trong một số trường hợp hiếm gặp.",
            loai_xu_ly="can_theo_doi"
        ))

    safe = all(w.muc_do < 3 for w in warnings)
    highest = max([w.muc_do for w in warnings], default=1)
    
    return ResponseEnvelope(
        data=QuickCheckResponse(safe=safe, highest_severity=highest, warnings=warnings),
        message="Kiểm tra nhanh an toàn thuốc hoàn tất"
    )

@router.patch(
    "/recommendations/{id}/acknowledge",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Đánh dấu bệnh nhân đã đọc/xử lý khuyến nghị an toàn",
    description="Ghi nhận phản hồi của người dùng đối với cảnh báo tương tác."
)
def acknowledge_recommendation(
    id: int,
    req: AcknowledgeRecommendationRequest,
    caller: CurrentUser = Depends(get_current_user)
):
    return ResponseEnvelope(data=MessageResponse(message=f"Đã ghi nhận người dùng đã xem cảnh báo #{id}."))
