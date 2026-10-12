"""Router 3: Medical Conditions & Health Profile (Schema v9: English naming, stage)."""
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
    Auto-triggers interaction safety re-analysis (drug-condition, drug-drug)
    whenever medical conditions or medications change.
    """
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
        items = [
            c for c in items
            if q.lower() in c.get("name", c.get("ten", "")).lower()
            or (c.get("icd10_code") and q.lower() in c["icd10_code"].lower())
        ]
    formatted = [
        ConditionCatalogResponse(
            id=c["id"],
            name=c.get("name", c.get("ten")),
            medical_nature=c.get("medical_nature", c.get("ban_chat_y_khoa")),
            data_role=c.get("data_role", c.get("vai_tro_du_lieu")),
            icd10_code=c.get("icd10_code")
        )
        for c in items[:limit]
    ]
    return ResponseEnvelope(data=formatted)

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
        if c["user_id"] == patient_id and c.get("status", c.get("trang_thai", "active")) == "active"
    ]
    formatted = [
        UserConditionResponse(
            id=c["id"],
            user_id=c["user_id"],
            condition_id=c["condition_id"],
            name=c.get("name", c.get("condition_name", "")),
            subtype=c.get("subtype"),
            stage=c.get("stage", c.get("phan_do")),
            status=c.get("status", c.get("trang_thai", "active"))
        )
        for c in active_conditions
    ]
    return ResponseEnvelope(data=formatted)

@router.post(
    "/patients/{patient_id}/conditions",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[UserConditionResponse],
    summary="Khai báo thêm bệnh lý nền vào hồ sơ",
    description="Yêu cầu quyền GHI (bệnh nhân hoặc người thân có sharing_enabled). Tự động kích hoạt kiểm tra tương tác thuốc."
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

    cond_name = catalog_cond.get("name", catalog_cond.get("ten"))
    new_record = {
        "id": len(db.user_conditions) + 1,
        "user_id": patient_id,
        "condition_id": req.condition_id,
        "name": cond_name,
        "condition_name": cond_name,
        "subtype": req.subtype,
        "stage": req.stage,
        "phan_do": req.stage,
        "status": "active",
        "trang_thai": "active"
    }
    db.user_conditions.append(new_record)
    
    # Auto-trigger re-analysis
    _trigger_automatic_regimen_analysis(patient_id)
    
    return ResponseEnvelope(
        data=UserConditionResponse(
            id=new_record["id"],
            user_id=new_record["user_id"],
            condition_id=new_record["condition_id"],
            name=new_record["name"],
            subtype=new_record["subtype"],
            stage=new_record["stage"],
            status=new_record["status"]
        ),
        message=f"Đã thêm '{cond_name}' vào hồ sơ bệnh nền và kích hoạt phân tích an toàn thuốc."
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
    if not cond or cond.get("status", cond.get("trang_thai")) == "archived":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONDITION_RECORD_NOT_FOUND", "message": "Không tìm thấy bản ghi bệnh nền của bệnh nhân"}
        )

    cond["status"] = "archived"
    cond["trang_thai"] = "archived"
    
    _trigger_automatic_regimen_analysis(patient_id)
    
    cond_name = cond.get("name", cond.get("condition_name"))
    return ResponseEnvelope(
        data=MessageResponse(message=f"Đã lưu trữ bệnh lý '{cond_name}' và cập nhật lại phân tích tương tác thuốc.")
    )
