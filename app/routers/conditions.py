"""Router 3: Medical Conditions & Health Profile."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status, HTTPException
from app.schemas.common import ResponseEnvelope, MessageResponse
from app.schemas.conditions import ConditionCatalogResponse, UserConditionCreate, UserConditionResponse
from app.core.security import CurrentUser, get_current_user
from app.core.access_control import require_patient_read, require_patient_write
from app.mock_db import db

router = APIRouter(prefix="", tags=["3. Medical Conditions"])

def _trigger_automatic_regimen_analysis(patient_id: str):
    """
    # TODO: implement real logic
    Auto-triggers interaction safety re-analysis (drug-condition, drug-drug)
    whenever medical conditions or medications change.
    """
    # In scaffolding, ensure snapshot exists/updates
    pass

@router.get(
    "/conditions",
    response_model=ResponseEnvelope[List[ConditionCatalogResponse]],
    summary="Tra cứu danh mục điều kiện bệnh lý nền chuẩn hóa (Bảng B)",
    description="Tra cứu danh mục bệnh theo tên hoặc mã ICD-10 (Tiểu đường, Suy thận, Tăng huyết áp, Loét dạ dày...)"
)
def search_condition_catalog(
    q: Optional[str] = Query(None, description="Từ khóa tìm kiếm"),
    limit: int = Query(20, ge=1, le=100)
):
    items = db.conditions
    if q:
        items = [c for c in items if q.lower() in c["ten"].lower() or (c.get("icd10_code") and q.lower() in c["icd10_code"].lower())]
    return ResponseEnvelope(data=[ConditionCatalogResponse(**c) for c in items[:limit]])

@router.get(
    "/patients/{patient_id}/conditions",
    response_model=ResponseEnvelope[List[UserConditionResponse]],
    summary="Lấy danh sách bệnh lý nền của bệnh nhân",
    description="Yêu cầu quyền ĐỌC (bệnh nhân, người thân có liên kết active, hoặc admin)."
)
def get_patient_conditions(
    patient_id: str,
    actor_role: str = Depends(require_patient_read("ho_so_suc_khoe"))
):
    active_conditions = [
        c for c in db.user_conditions
        if c["user_id"] == patient_id and c.get("trang_thai", "active") == "active"
    ]
    return ResponseEnvelope(data=[UserConditionResponse(**c) for c in active_conditions])

@router.post(
    "/patients/{patient_id}/conditions",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[UserConditionResponse],
    summary="Khai báo thêm bệnh lý nền vào hồ sơ",
    description="Yêu cầu quyền GHI (bệnh nhân, hoặc người thân có cho_phep_chinh_sua=True). Tự động kích hoạt kiểm tra tương tác thuốc."
)
def add_patient_condition(
    patient_id: str,
    req: UserConditionCreate,
    actor_role: str = Depends(require_patient_write("ho_so_suc_khoe"))
):
    catalog_cond = next((c for c in db.conditions if c["id"] == req.condition_id), None)
    if not catalog_cond:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONDITION_NOT_FOUND", "message": f"Không tìm thấy bệnh lý mã #{req.condition_id} trong danh mục"}
        )

    new_record = {
        "id": len(db.user_conditions) + 1,
        "user_id": patient_id,
        "condition_id": req.condition_id,
        "condition_name": catalog_cond["ten"],
        "subtype": req.subtype,
        "phan_do": req.phan_do,
        "trang_thai": "active"
    }
    db.user_conditions.append(new_record)
    
    # Auto-trigger re-analysis
    _trigger_automatic_regimen_analysis(patient_id)
    
    return ResponseEnvelope(
        data=UserConditionResponse(**new_record),
        message=f"Đã thêm '{catalog_cond['ten']}' vào hồ sơ bệnh nền và kích hoạt phân tích an toàn thuốc."
    )

@router.delete(
    "/patients/{patient_id}/conditions/{id}",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Xóa (soft-delete) bệnh lý nền khỏi hồ sơ",
    description="Chuyển trạng thái sang 'archived' để bảo tồn vết y khoa. Tự động kích hoạt kiểm tra tương tác thuốc."
)
def delete_patient_condition(
    patient_id: str,
    id: int,
    actor_role: str = Depends(require_patient_write("ho_so_suc_khoe"))
):
    cond = next((c for c in db.user_conditions if c["id"] == id and c["user_id"] == patient_id), None)
    if not cond or cond.get("trang_thai") == "archived":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONDITION_RECORD_NOT_FOUND", "message": "Không tìm thấy bản ghi bệnh nền của bệnh nhân"}
        )

    # Soft delete
    cond["trang_thai"] = "archived"
    
    # Auto-trigger re-analysis
    _trigger_automatic_regimen_analysis(patient_id)
    
    return ResponseEnvelope(
        data=MessageResponse(message=f"Đã lưu trữ bệnh lý '{cond['condition_name']}' và cập nhật lại phân tích tương tác thuốc.")
    )
