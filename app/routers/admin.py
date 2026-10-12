"""Router 9: Admin Portal, Drug Catalog CRUD, and Compliance Operations (Schema v9)."""
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, status, HTTPException
from app.schemas.common import ResponseEnvelope, MessageResponse, PaginatedData, PaginationMeta
from app.schemas.prescriptions import MedicationCatalogResponse
from app.schemas.admin import (
    AdminMedicationCreate, AdminMedicationUpdate, SyncTriggerResponse,
    SyncStatusResponse, AuditLogResponse,
    AuditPostReviewRequest, AuditPostReviewData, RuleChangeLogResponse,
    ProcessDeletionRequest, DpiaRecordResponse, DpiaRecordCreate
)
from app.schemas.consents import DataDeletionRequestResponse
from app.schemas.conditions import ConditionCatalogResponse
from app.core.security import CurrentUser, require_admin_user
from app.mock_db import db, current_time_iso

router = APIRouter(prefix="", tags=["9. Admin Operations"])

# --- Catalog Management ---

@router.get(
    "/admin/medications",
    response_model=ResponseEnvelope[PaginatedData[MedicationCatalogResponse]],
    summary="Danh sách danh mục thuốc thương mại (Admin, Phân trang)",
    description="Tra cứu và quản lý toàn bộ danh mục thuốc của hệ thống (Schema v9: medications)."
)
def admin_list_medications(
    q: Optional[str] = Query(None, description="Tìm theo tên thuốc hoặc hoạt chất"),
    include_deleted: bool = Query(False, description="Bao gồm cả các thuốc đã xóa mềm"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user)
):
    items = db.medications
    if not include_deleted:
        items = [m for m in items if m.get("deleted_at") is None]
    if q:
        items = [
            m for m in items
            if q.lower() in m.get("name", m.get("ten_thuoc", "")).lower()
            or (m.get("raw_active_ingredient") and q.lower() in m["raw_active_ingredient"].lower())
            or (m.get("hoat_chat_raw") and q.lower() in m["hoat_chat_raw"].lower())
        ]
    
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = [
        MedicationCatalogResponse(
            id=m["id"],
            name=m.get("name", m.get("ten_thuoc")),
            raw_active_ingredient=m.get("raw_active_ingredient", m.get("hoat_chat_raw")),
            strength_text=m.get("strength_text", m.get("ham_luong")),
            dosage_form=m.get("dosage_form", m.get("dang_bao_che")),
            manufacturer_name=m.get("manufacturer_name", m.get("cty_san_xuat_ten")),
            manufacturer_country=m.get("manufacturer_country", m.get("cty_san_xuat_nuoc")),
            packaging_spec=m.get("packaging_spec", m.get("quy_cach_dong_goi")),
            deleted_at=m.get("deleted_at")
        )
        for m in items[start:start+page_size]
    ]
    
    return ResponseEnvelope(
        data=PaginatedData(items=paged, pagination=PaginationMeta(page=page, page_size=page_size, total_items=total, total_pages=pages))
    )

@router.post(
    "/admin/medications",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[MedicationCatalogResponse],
    summary="Thêm thuốc mới vào catalog",
    description="Tạo mới bản ghi thuốc thương phẩm trong catalog quốc gia (Schema v9: medications)."
)
def admin_create_medication(
    req: AdminMedicationCreate,
    admin: CurrentUser = Depends(require_admin_user)
):
    new_id = max([m["id"] for m in db.medications], default=100) + 1
    new_med = {
        "id": new_id,
        "name": req.name,
        "ten_thuoc": req.name,
        "raw_active_ingredient": req.raw_active_ingredient,
        "hoat_chat_raw": req.raw_active_ingredient,
        "strength_text": req.strength_text,
        "ham_luong": req.strength_text,
        "dosage_form": req.dosage_form,
        "dang_bao_che": req.dosage_form,
        "manufacturer_name": req.manufacturer_name,
        "cty_san_xuat_ten": req.manufacturer_name,
        "manufacturer_country": req.manufacturer_country,
        "cty_san_xuat_nuoc": req.manufacturer_country,
        "packaging_spec": req.packaging_spec,
        "quy_cach_dong_goi": req.packaging_spec,
        "deleted_at": None,
        "active_ingredients": []
    }
    db.medications.append(new_med)
    return ResponseEnvelope(
        data=MedicationCatalogResponse(
            id=new_med["id"],
            name=new_med["name"],
            raw_active_ingredient=new_med["raw_active_ingredient"],
            strength_text=new_med["strength_text"],
            dosage_form=new_med["dosage_form"],
            manufacturer_name=new_med["manufacturer_name"],
            manufacturer_country=new_med["manufacturer_country"],
            packaging_spec=new_med["packaging_spec"],
            deleted_at=None
        ),
        message="Thêm thuốc vào catalog thành công"
    )

@router.put(
    "/admin/medications/{id}",
    response_model=ResponseEnvelope[MedicationCatalogResponse],
    summary="Cập nhật thuốc trong catalog",
    description="Chỉnh sửa thông tin chi tiết của thuốc."
)
def admin_update_medication(
    id: int,
    req: AdminMedicationUpdate,
    admin: CurrentUser = Depends(require_admin_user)
):
    med = next((m for m in db.medications if m["id"] == id), None)
    if not med:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc"})
    
    if req.name is not None:
        med["name"] = req.name
        med["ten_thuoc"] = req.name
    if req.strength_text is not None:
        med["strength_text"] = req.strength_text
        med["ham_luong"] = req.strength_text
    if req.raw_active_ingredient is not None:
        med["raw_active_ingredient"] = req.raw_active_ingredient
        med["hoat_chat_raw"] = req.raw_active_ingredient
    if req.dosage_form is not None:
        med["dosage_form"] = req.dosage_form
        med["dang_bao_che"] = req.dosage_form
    if req.manufacturer_name is not None:
        med["manufacturer_name"] = req.manufacturer_name
        med["cty_san_xuat_ten"] = req.manufacturer_name
    if req.manufacturer_country is not None:
        med["manufacturer_country"] = req.manufacturer_country
        med["cty_san_xuat_nuoc"] = req.manufacturer_country
    if req.packaging_spec is not None:
        med["packaging_spec"] = req.packaging_spec
        med["quy_cach_dong_goi"] = req.packaging_spec

    return ResponseEnvelope(
        data=MedicationCatalogResponse(
            id=med["id"],
            name=med.get("name", med.get("ten_thuoc")),
            raw_active_ingredient=med.get("raw_active_ingredient", med.get("hoat_chat_raw")),
            strength_text=med.get("strength_text", med.get("ham_luong")),
            dosage_form=med.get("dosage_form", med.get("dang_bao_che")),
            manufacturer_name=med.get("manufacturer_name", med.get("cty_san_xuat_ten")),
            manufacturer_country=med.get("manufacturer_country", med.get("cty_san_xuat_nuoc")),
            packaging_spec=med.get("packaging_spec", med.get("quy_cach_dong_goi")),
            deleted_at=med.get("deleted_at")
        ),
        message="Cập nhật thuốc thành công"
    )

@router.delete(
    "/admin/medications/{id}",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Xóa mềm thuốc khỏi catalog (Schema v9: soft delete)",
    description="Đánh dấu deleted_at = now() để giữ tính toàn vẹn tham chiếu lịch sử đơn thuốc."
)
def admin_delete_medication(id: int, admin: CurrentUser = Depends(require_admin_user)):
    med = next((m for m in db.medications if m["id"] == id), None)
    if not med:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc"})
    
    med["deleted_at"] = current_time_iso()
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xóa mềm thuốc #{id} khỏi catalog."))

# --- Active Ingredients (Table A) ---
@router.get("/admin/active-ingredients", response_model=ResponseEnvelope[List[Dict[str, Any]]], summary="Quản lý hoạt chất chuẩn hóa (Bảng A)")
def admin_list_active_ingredients(admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=[
        {"id": 1, "standard_name": "Metformin", "role": "dieu_tri_benh_nen", "atc_code": "A10BA02", "pharmacological_group": "Biguanides"},
        {"id": 2, "standard_name": "Amlodipine", "role": "dieu_tri_benh_nen", "atc_code": "C08CA01", "pharmacological_group": "Calcium channel blockers"},
        {"id": 3, "standard_name": "Paracetamol", "role": "trieu_chung_cap_tinh", "atc_code": "N02BE01", "pharmacological_group": "Anilides"}
    ])

@router.post("/admin/active-ingredients", status_code=status.HTTP_201_CREATED, response_model=ResponseEnvelope[MessageResponse], summary="Tạo hoạt chất Bảng A")
def admin_create_active_ingredient(data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message="Tạo hoạt chất thành công"))

@router.put("/admin/active-ingredients/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Sửa hoạt chất Bảng A")
def admin_update_active_ingredient(id: int, data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Cập nhật hoạt chất #{id} thành công"))

@router.delete("/admin/active-ingredients/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Xóa hoạt chất Bảng A")
def admin_delete_active_ingredient(id: int, admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xóa hoạt chất #{id}"))

# --- Conditions (Table B) ---
@router.get("/admin/conditions", response_model=ResponseEnvelope[List[ConditionCatalogResponse]], summary="Quản lý điều kiện bệnh lý nền (Bảng B)")
def admin_list_conditions(admin: CurrentUser = Depends(require_admin_user)):
    formatted = [
        ConditionCatalogResponse(
            id=c["id"],
            name=c.get("name", c.get("ten")),
            medical_nature=c.get("medical_nature", c.get("ban_chat_y_khoa")),
            data_role=c.get("data_role", c.get("vai_tro_du_lieu")),
            icd10_code=c.get("icd10_code")
        )
        for c in db.conditions
    ]
    return ResponseEnvelope(data=formatted)

@router.post("/admin/conditions", status_code=status.HTTP_201_CREATED, response_model=ResponseEnvelope[MessageResponse], summary="Tạo bệnh lý nền Bảng B")
def admin_create_condition(data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message="Tạo bệnh lý nền thành công"))

@router.put("/admin/conditions/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Sửa bệnh lý nền Bảng B")
def admin_update_condition(id: int, data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Cập nhật bệnh lý #{id} thành công"))

@router.delete("/admin/conditions/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Xóa bệnh lý nền Bảng B")
def admin_delete_condition(id: int, admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xóa bệnh lý #{id}"))

# --- Interactions & Food Interactions (Table C & D) ---
@router.get("/admin/interactions", response_model=ResponseEnvelope[List[Dict[str, Any]]], summary="Quản lý cặp tương tác thuốc - thuốc (Bảng C)")
def admin_list_interactions(admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=[
        {
            "id": 1,
            "ingredient_a_id": 1,
            "ingredient_b_id": 10,
            "interaction_type": "phu_thuoc_lieu",
            "severity_level": 2,
            "handling_type": "can_theo_doi",
            "description": "Tương tác phụ thuộc liều giữa Metformin và Cimetidine",
            "deleted_at": None
        }
    ])

@router.post("/admin/interactions", status_code=status.HTTP_201_CREATED, response_model=ResponseEnvelope[MessageResponse], summary="Tạo cặp tương tác thuốc")
def admin_create_interaction(data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message="Thêm cặp tương tác thuốc thành công"))

@router.put("/admin/interactions/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Sửa cặp tương tác thuốc")
def admin_update_interaction(id: int, data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Cập nhật tương tác #{id} thành công"))

@router.delete("/admin/interactions/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Xóa cặp tương tác thuốc (soft-delete)")
def admin_delete_interaction(id: int, admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xóa tương tác #{id}"))

@router.get("/admin/drug-foods", response_model=ResponseEnvelope[List[Dict[str, Any]]], summary="Quản lý tương tác thuốc - thực phẩm (Bảng D)")
def admin_list_drug_foods(admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=[
        {
            "id": 1,
            "active_ingredient_id": 2,
            "food_to_avoid": "Nước bưởi chùm",
            "severity_level": 2,
            "reason": "Tăng nồng độ Amlodipine trong máu gây tụt huyết áp",
            "deleted_at": None
        }
    ])

@router.post("/admin/drug-foods", status_code=status.HTTP_201_CREATED, response_model=ResponseEnvelope[MessageResponse], summary="Thêm tương tác thuốc - thực phẩm")
def admin_create_drug_food(data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message="Thêm tương tác thực phẩm thành công"))

@router.put("/admin/drug-foods/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Sửa tương tác thuốc - thực phẩm")
def admin_update_drug_food(id: int, data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Cập nhật tương tác thực phẩm #{id} thành công"))

@router.delete("/admin/drug-foods/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Xóa tương tác thuốc - thực phẩm (soft-delete)")
def admin_delete_drug_food(id: int, admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xóa tương tác thực phẩm #{id}"))

# --- Catalog Sync Operations (catalog_sync_runs) ---
@router.post(
    "/admin/catalog/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResponseEnvelope[SyncTriggerResponse],
    summary="Kích hoạt job ETL đồng bộ dữ liệu Cục Quản lý Dược",
    description="Kích hoạt tiến trình đồng bộ nền từ nguồn dav_drugbank, qd_5948, hoặc duoc_thu_qg (PB06, Schema v9)."
)
def trigger_catalog_sync(
    source: str = Query("qd_5948", pattern="^(dav_drugbank|qd_5948|duoc_thu_qg)$"),
    admin: CurrentUser = Depends(require_admin_user)
):
    new_run = {
        "id": len(db.catalog_sync_runs) + 1,
        "source": source,
        "started_at": current_time_iso(),
        "finished_at": None,
        "status": "dang_chay",
        "records_inserted": 0,
        "records_updated": 0,
        "records_failed": 0,
        "error_details": None,
        "triggered_by": "admin_thu_cong"
    }
    db.catalog_sync_runs.append(new_run)
    return ResponseEnvelope(
        data=SyncTriggerResponse(job_id=f"sync-run-{new_run['id']}", status="dang_chay", source=source), # type: ignore
        message="Job đồng bộ danh mục dược phẩm đã được gửi vào hàng đợi xử lý nền."
    )

@router.get(
    "/admin/catalog/sync-status",
    response_model=ResponseEnvelope[SyncStatusResponse],
    summary="Xem trạng thái lượt đồng bộ catalog gần nhất (catalog_sync_runs)",
    description="Kiểm tra tiến độ số lượng thuốc và hoạt chất từ bảng catalog_sync_runs."
)
def get_catalog_sync_status(admin: CurrentUser = Depends(require_admin_user)):
    latest = db.catalog_sync_runs[-1] if db.catalog_sync_runs else {
        "id": 1,
        "source": "qd_5948",
        "started_at": current_time_iso(),
        "finished_at": current_time_iso(),
        "status": "thanh_cong",
        "records_inserted": 1250,
        "records_updated": 48,
        "records_failed": 0,
        "error_details": None,
        "triggered_by": "scheduler"
    }
    return ResponseEnvelope(data=SyncStatusResponse(**latest))

# --- Rule Change Logs ---
@router.get(
    "/admin/rule-change-logs",
    response_model=ResponseEnvelope[PaginatedData[RuleChangeLogResponse]],
    summary="Tra cứu nhật ký thay đổi luật tương tác & catalog (Phân trang, Rollback Audit)",
    description="Truy vết toàn bộ các thay đổi về ngưỡng liều, cặp tương tác thuốc/thức ăn và cấu hình danh mục y tế."
)
def list_rule_change_logs(
    table_name: Optional[str] = Query(None, description="Tên bảng dữ liệu luật (active_ingredient_interactions, drug_food_interactions...)"),
    changed_by: Optional[str] = Query(None, description="ID Admin thực hiện thay đổi"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user)
):
    items = getattr(db, "rule_change_logs", [])
    if table_name:
        items = [r for r in items if r["table_name"] == table_name]
    if changed_by:
        items = [r for r in items if r["changed_by"] == changed_by]
    if from_date:
        items = [r for r in items if r["changed_at"] >= from_date]
    if to_date:
        items = [r for r in items if r["changed_at"] <= to_date]

    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = [RuleChangeLogResponse(**r) for r in items[start:start+page_size]]

    return ResponseEnvelope(
        data=PaginatedData(
            items=paged,
            pagination=PaginationMeta(page=page, page_size=page_size, total_items=total, total_pages=pages)
        )
    )

# --- Compliance & Audit Logging ---
@router.get(
    "/admin/audit-logs",
    response_model=ResponseEnvelope[PaginatedData[AuditLogResponse]],
    summary="Tra cứu nhật ký truy cập dữ liệu nhạy cảm (Phân trang - NFR06, QA.09)",
    description="Tra cứu vết kiểm toán append-only mọi truy cập vào dữ liệu bệnh nhân của Admin và Người thân (Schema v9: không có self)."
)
def search_audit_logs(
    patient_id: Optional[str] = Query(None, description="Lọc theo bệnh nhân"),
    actor_user_id: Optional[str] = Query(None, description="Lọc theo người truy cập (Index QA.09 Schema v9)"),
    actor_role: Optional[str] = Query(None, description="Lọc theo role: family, admin, khong_co_quyen"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    is_emergency_override: Optional[bool] = Query(None, description="Lọc thao tác can thiệp khẩn cấp"),
    review_status: Optional[str] = Query(None, description="pending_post_review, reviewed_valid, reviewed_invalid"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user)
):
    items = db.access_logs
    if patient_id:
        items = [l for l in items if l.get("patient_user_id") == patient_id]
    if actor_user_id:
        items = [l for l in items if l.get("actor_user_id") == actor_user_id]
    if actor_role:
        items = [l for l in items if l.get("actor_role") == actor_role]
    if from_date:
        items = [l for l in items if l.get("accessed_at", l.get("thoi_gian", "")) >= from_date]
    if to_date:
        items = [l for l in items if l.get("accessed_at", l.get("thoi_gian", "")) <= to_date]
    if is_emergency_override is not None:
        items = [l for l in items if l.get("is_emergency_override") == is_emergency_override]
    if review_status:
        items = [l for l in items if l.get("review_status") == review_status]

    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = [
        AuditLogResponse(
            id=l["id"],
            actor_user_id=l["actor_user_id"],
            actor_role=l.get("actor_role", "khong_co_quyen"),
            patient_user_id=l["patient_user_id"],
            data_scope=l["data_scope"],
            result=l.get("result", l.get("ket_qua", "allowed")),
            rejection_reason=l.get("rejection_reason", l.get("ly_do_tu_choi")),
            override_reason=l.get("override_reason", l.get("ly_do_can_thiep")),
            action=l.get("action"),
            is_emergency_override=l.get("is_emergency_override", False),
            review_status=l.get("review_status"),
            review_deadline=l.get("review_deadline"),
            reviewer_user_id=l.get("reviewer_user_id"),
            target_audit_log_id=l.get("target_audit_log_id"),
            review_decision=l.get("review_decision"),
            review_note=l.get("review_note"),
            compliance_flags=l.get("compliance_flags", []),
            accessed_at=l.get("accessed_at", l.get("thoi_gian", current_time_iso()))
        )
        for l in items[start:start+page_size]
    ]

    return ResponseEnvelope(
        data=PaginatedData(
            items=paged,
            pagination=PaginationMeta(page=page, page_size=page_size, total_items=total, total_pages=pages)
        )
    )

@router.post(
    "/admin/audit-logs/{id}/post-review",
    response_model=ResponseEnvelope[AuditPostReviewData],
    summary="Xác nhận hậu kiểm Four-Eyes trong 24h cho can thiệp khẩn cấp (Hỗ trợ 3 trạng thái & 5 Guardrails)",
    description="Admin thứ 2 độc lập thực hiện hậu kiểm thao tác can thiệp khẩn cấp của Admin khác trong vòng 24 giờ."
)
def post_review_emergency_audit_log(
    id: int,
    req: AuditPostReviewRequest,
    admin: CurrentUser = Depends(require_admin_user)
):
    audit_log = next((l for l in db.access_logs if l["id"] == id), None)
    if not audit_log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "AUDIT_LOG_NOT_FOUND", "message": "Không tìm thấy bản ghi nhật ký kiểm toán"})

    # Guardrail 2: Anti-self review
    if admin.user_id == audit_log.get("actor_user_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CANNOT_REVIEW_OWN_ACTION",
                "message": "Quản trị viên không được tự hậu kiểm thao tác do chính mình thực hiện."
            }
        )

    # Guardrail 3: Must be emergency override
    if not audit_log.get("is_emergency_override"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REVIEW_NOT_REQUIRED",
                "message": "Bản ghi này không phải thao tác can thiệp khẩn cấp cần hậu kiểm."
            }
        )

    # Guardrail 4: Must be pending review
    if audit_log.get("review_status") != "pending_post_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REVIEW_ALREADY_COMPLETED",
                "message": "Bản ghi can thiệp này đã được hậu kiểm trước đó."
            }
        )

    # Guardrail 5: Must be within 24h deadline
    deadline = audit_log.get("review_deadline")
    if deadline and current_time_iso() > deadline:
        audit_log.setdefault("compliance_flags", []).append("POST_REVIEW_OVERDUE")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "POST_REVIEW_DEADLINE_EXCEEDED",
                "message": "Đã quá thời hạn 24 giờ cho phép hậu kiểm."
            }
        )

    new_status = "reviewed_valid" if req.decision == "valid" else "reviewed_invalid"
    audit_log["review_status"] = new_status
    audit_log["reviewer_user_id"] = admin.user_id
    audit_log["reviewed_at"] = current_time_iso()
    audit_log["review_note"] = req.review_note

    if req.decision == "invalid":
        audit_log.setdefault("compliance_flags", []).append("COMPLIANCE_REVIEW_REQUIRED")
        db.notifications.append({
            "id": len(db.notifications) + 1,
            "user_id": "usr-admin-1",
            "about_patient_user_id": audit_log.get("patient_user_id", ""),
            "type": "canh_bao_compliance",
            "content": f"Cảnh báo tuân thủ: Thao tác can thiệp khẩn cấp #{id} của Admin {audit_log.get('actor_user_id')} bị đánh giá KHÔNG HỢP LỆ bởi {admin.user_id}. Ghi chú: {req.review_note}.",
            "is_read": False,
            "dedupe_key": None,
            "created_at": current_time_iso(),
            # Compatibility
            "ve_patient_user_id": audit_log.get("patient_user_id", ""),
            "loai": "canh_bao_compliance",
            "noi_dung": f"Cảnh báo tuân thủ: Thao tác can thiệp khẩn cấp #{id} của Admin {audit_log.get('actor_user_id')} bị đánh giá KHÔNG HỢP LỆ bởi {admin.user_id}. Ghi chú: {req.review_note}.",
            "da_doc": False,
            "thoi_gian": current_time_iso()
        })

    review_event = {
        "id": len(db.access_logs) + 1,
        "actor_user_id": admin.user_id,
        "actor_role": "admin",
        "patient_user_id": audit_log.get("patient_user_id", ""),
        "data_scope": "admin",
        "action": "POST_REVIEW",
        "target_audit_log_id": id,
        "review_decision": req.decision,
        "review_note": req.review_note,
        "result": "allowed",
        "accessed_at": current_time_iso(),
        "ket_qua": "allowed",
        "thoi_gian": current_time_iso()
    }
    db.access_logs.append(review_event)

    return ResponseEnvelope(
        data=AuditPostReviewData(review_status=new_status),
        message="Đã hoàn tất hậu kiểm."
    )

@router.get(
    "/admin/data-deletion-requests",
    response_model=ResponseEnvelope[PaginatedData[DataDeletionRequestResponse]],
    summary="Danh sách yêu cầu xóa dữ liệu cá nhân chờ duyệt (NĐ 356, QA.01)",
    description="Xem các yêu cầu xóa dữ liệu của người dùng."
)
def list_data_deletion_requests(
    status: Optional[str] = Query(None, alias="status", description="cho_duyet, da_duyet, tu_choi, hoan_tat"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user)
):
    items = db.data_deletion_requests
    if status:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = [DataDeletionRequestResponse(**r) for r in items[start:start+page_size]]

    return ResponseEnvelope(
        data=PaginatedData(
            items=paged,
            pagination=PaginationMeta(page=page, page_size=page_size, total_items=total, total_pages=pages)
        )
    )

@router.post(
    "/admin/data-deletion-requests/{id}/process",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Xử lý duyệt hoặc từ chối yêu cầu xóa dữ liệu (CD9)",
    description="Admin phê duyệt (da_duyet) hoặc từ chối (tu_choi kèm lý do bắt buộc). Khi duyệt, tiến trình worker thực thi xóa và biến user thành tombstone."
)
def process_data_deletion_request(
    id: int,
    req: ProcessDeletionRequest,
    admin: CurrentUser = Depends(require_admin_user)
):
    r = next((req_item for req_item in db.data_deletion_requests if req_item["id"] == id), None)
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "REQUEST_NOT_FOUND", "message": "Không tìm thấy yêu cầu"})
    
    if req.action == "reject" and not req.rejection_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "REJECTION_REASON_REQUIRED", "message": "Từ chối yêu cầu xóa dữ liệu bắt buộc phải có lý do (rejection_reason)."}
        )

    now = current_time_iso()
    if req.action == "approve":
        r["status"] = "da_duyet"
        r["handled_by_admin_id"] = admin.user_id
        r["handled_at"] = now
        r["completed_at"] = now
        r["last_error"] = None

        # Execute erasure simulation (CD9, DW3): user becomes tombstone
        user = db.users.get(r["user_id"])
        if user:
            user["erased_at"] = now
            user["full_name"] = None
            user["ho_ten"] = None
            user["date_of_birth"] = None
            user["ngay_sinh"] = None
            user["gender"] = None
            user["gioi_tinh"] = None
            user["phone_number"] = None
            user["so_dien_thoai"] = None
            user["email"] = None
        r["status"] = "hoan_tat"
    else:
        r["status"] = "tu_choi"
        r["rejection_reason"] = req.rejection_reason
        r["handled_by_admin_id"] = admin.user_id
        r["handled_at"] = now

    status_str = "đã phê duyệt và hoàn tất xóa" if req.action == "approve" else "đã từ chối"
    return ResponseEnvelope(data=MessageResponse(message=f"Yêu cầu #{id} {status_str} thành công."))

# --- DPIA Records ---
@router.get(
    "/admin/dpia-records",
    response_model=ResponseEnvelope[List[DpiaRecordResponse]],
    summary="Danh sách hồ sơ đánh giá tác động riêng tư (DPIA)",
    description="Hồ sơ luồng dữ liệu nhạy cảm theo quy định bảo vệ dữ liệu."
)
def list_dpia_records(admin: CurrentUser = Depends(require_admin_user)):
    formatted = [
        DpiaRecordResponse(
            id=d["id"],
            data_flow_name=d.get("data_flow_name", d.get("ten_luong_du_lieu")),
            has_cross_border_transfer=d.get("has_cross_border_transfer", d.get("co_chuyen_du_lieu_xuyen_bien_gioi", False)),
            status=d.get("status", d.get("trang_thai")),
            approved_by_id=d.get("approved_by_id", d.get("nguoi_phe_duyet_id")),
            approval_date=d.get("approval_date", d.get("ngay_phe_duyet"))
        )
        for d in db.dpia_records
    ]
    return ResponseEnvelope(data=formatted)

@router.post(
    "/admin/dpia-records",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[DpiaRecordResponse],
    summary="Tạo mới hồ sơ DPIA",
    description="Khai báo luồng dữ liệu nhạy cảm mới phục vụ đánh giá tuân thủ."
)
def create_dpia_record(req: DpiaRecordCreate, admin: CurrentUser = Depends(require_admin_user)):
    new_record = {
        "id": len(db.dpia_records) + 1,
        "data_flow_name": req.data_flow_name,
        "ten_luong_du_lieu": req.data_flow_name,
        "has_cross_border_transfer": req.has_cross_border_transfer,
        "co_chuyen_du_lieu_xuyen_bien_gioi": req.has_cross_border_transfer,
        "status": req.status,
        "trang_thai": req.status,
        "approved_by_id": None,
        "approval_date": None
    }
    db.dpia_records.append(new_record)
    return ResponseEnvelope(
        data=DpiaRecordResponse(
            id=new_record["id"],
            data_flow_name=new_record["data_flow_name"],
            has_cross_border_transfer=new_record["has_cross_border_transfer"],
            status=new_record["status"]
        ),
        message="Tạo hồ sơ DPIA thành công"
    )
