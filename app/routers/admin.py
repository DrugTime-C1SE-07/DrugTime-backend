"""Router 9: Admin Portal, Drug Catalog CRUD, and Compliance Operations."""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, status, HTTPException
from app.schemas.common import ResponseEnvelope, MessageResponse, PaginatedData, PaginationMeta
from app.schemas.prescriptions import MedicationCatalogResponse
from app.schemas.admin import (
    AdminMedicationCreate, AdminMedicationUpdate, SyncTriggerResponse,
    SyncStatusResponse, ResolveUnmatchedScanRequest, AuditLogResponse,
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
    description="Tra cứu và quản lý toàn bộ danh mục thuốc của hệ thống."
)
def admin_list_medications(
    q: Optional[str] = Query(None, description="Tìm theo tên thuốc hoặc hoạt chất"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user)
):
    items = db.medications
    if q:
        items = [m for m in items if q.lower() in m["ten_thuoc"].lower() or (m.get("hoat_chat_raw") and q.lower() in m["hoat_chat_raw"].lower())]
    
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = [MedicationCatalogResponse(**m) for m in items[start:start+page_size]]
    
    return ResponseEnvelope(data=PaginatedData(items=paged, pagination=PaginationMeta(page=page, page_size=page_size, total_items=total, total_pages=pages)))

@router.post(
    "/admin/medications",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[MedicationCatalogResponse],
    summary="Thêm thuốc mới vào catalog",
    description="Tạo mới bản ghi thuốc thương phẩm trong catalog quốc gia."
)
def admin_create_medication(
    req: AdminMedicationCreate,
    admin: CurrentUser = Depends(require_admin_user)
):
    new_id = max([m["id"] for m in db.medications], default=100) + 1
    new_med = {
        "id": new_id,
        "ten_thuoc": req.ten_thuoc,
        "hoat_chat_raw": req.hoat_chat_raw,
        "ham_luong": req.ham_luong,
        "dang_bao_che": req.dang_bao_che,
        "cty_san_xuat_ten": req.cty_san_xuat_ten,
        "cty_san_xuat_nuoc": req.cty_san_xuat_nuoc,
        "quy_cach_dong_goi": req.quy_cach_dong_goi,
        "active_ingredients": []
    }
    db.medications.append(new_med)
    return ResponseEnvelope(data=MedicationCatalogResponse(**new_med), message="Thêm thuốc vào catalog thành công")

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
    
    if req.ten_thuoc is not None:
        med["ten_thuoc"] = req.ten_thuoc
    if req.ham_luong is not None:
        med["ham_luong"] = req.ham_luong
    if req.hoat_chat_raw is not None:
        med["hoat_chat_raw"] = req.hoat_chat_raw
    if req.dang_bao_che is not None:
        med["dang_bao_che"] = req.dang_bao_che

    return ResponseEnvelope(data=MedicationCatalogResponse(**med), message="Cập nhật thuốc thành công")

@router.delete(
    "/admin/medications/{id}",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Xóa thuốc khỏi catalog",
    description="Xóa thuốc khỏi danh mục thương phẩm."
)
def admin_delete_medication(id: int, admin: CurrentUser = Depends(require_admin_user)):
    db.medications[:] = [m for m in db.medications if m["id"] != id]
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xóa thuốc #{id} khỏi catalog."))

# --- Active Ingredients (Table A) ---
@router.get("/admin/active-ingredients", response_model=ResponseEnvelope[List[Dict[str, Any]]], summary="Quản lý hoạt chất chuẩn hóa (Bảng A)")
def admin_list_active_ingredients(admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=[
        {"id": 1, "ten_hoat_chat_chuan": "Metformin", "vai_tro": "dieu_tri_benh_nen", "atc_code": "A10BA02"},
        {"id": 2, "ten_hoat_chat_chuan": "Amlodipine", "vai_tro": "dieu_tri_benh_nen", "atc_code": "C08CA01"},
        {"id": 3, "ten_hoat_chat_chuan": "Paracetamol", "vai_tro": "trieu_chung_cap_tinh", "atc_code": "N02BE01"}
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
    return ResponseEnvelope(data=[ConditionCatalogResponse(**c) for c in db.conditions])

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
        {"id": 1, "hoat_chat_a": "Metformin", "hoat_chat_b": "Cimetidine", "loai_tuong_tac": "phu_thuoc_lieu", "muc_do": 2, "loai_xu_ly": "can_theo_doi"}
    ])

@router.post("/admin/interactions", status_code=status.HTTP_201_CREATED, response_model=ResponseEnvelope[MessageResponse], summary="Tạo cặp tương tác thuốc")
def admin_create_interaction(data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message="Thêm cặp tương tác thuốc thành công"))

@router.put("/admin/interactions/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Sửa cặp tương tác thuốc")
def admin_update_interaction(id: int, data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Cập nhật tương tác #{id} thành công"))

@router.delete("/admin/interactions/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Xóa cặp tương tác thuốc")
def admin_delete_interaction(id: int, admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xóa tương tác #{id}"))

@router.get("/admin/drug-foods", response_model=ResponseEnvelope[List[Dict[str, Any]]], summary="Quản lý tương tác thuốc - thực phẩm (Bảng D)")
def admin_list_drug_foods(admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=[
        {"id": 1, "hoat_chat": "Amlodipine", "thuc_pham_can_tranh": "Nước bưởi chùm", "muc_do": 2, "ly_do": "Tăng nồng độ thuốc trong máu"}
    ])

@router.post("/admin/drug-foods", status_code=status.HTTP_201_CREATED, response_model=ResponseEnvelope[MessageResponse], summary="Thêm tương tác thuốc - thực phẩm")
def admin_create_drug_food(data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message="Thêm tương tác thực phẩm thành công"))

@router.put("/admin/drug-foods/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Sửa tương tác thuốc - thực phẩm")
def admin_update_drug_food(id: int, data: Dict[str, Any], admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Cập nhật tương tác thực phẩm #{id} thành công"))

@router.delete("/admin/drug-foods/{id}", response_model=ResponseEnvelope[MessageResponse], summary="Xóa tương tác thuốc - thực phẩm")
def admin_delete_drug_food(id: int, admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xóa tương tác thực phẩm #{id}"))

# --- Catalog Sync Operations ---
@router.post(
    "/admin/catalog/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResponseEnvelope[SyncTriggerResponse],
    summary="Kích hoạt job ETL đồng bộ dữ liệu Cục Quản lý Dược",
    description="Kích hoạt tiến trình đồng bộ nền từ nguồn Dược thư Quốc gia Việt Nam (QĐ 5948/QĐ-BYT)."
)
def trigger_catalog_sync(admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(
        data=SyncTriggerResponse(job_id="sync-job-20260921-01", status="queued"),
        message="Job đồng bộ danh mục dược phẩm đã được gửi vào hàng đợi xử lý nền."
    )

@router.get(
    "/admin/catalog/sync-status",
    response_model=ResponseEnvelope[SyncStatusResponse],
    summary="Xem trạng thái tiến trình sync catalog nền",
    description="Kiểm tra tiến độ số lượng thuốc và hoạt chất đã cập nhật từ nguồn chính thống."
)
def get_catalog_sync_status(admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(
        data=SyncStatusResponse(
            job_id="sync-job-20260921-01",
            status="completed",
            records_processed=1250,
            records_updated=48,
            last_synced_at=current_time_iso()
        )
    )

# --- OCR Unmatched Scans Review ---
@router.get(
    "/admin/unmatched-scans",
    response_model=ResponseEnvelope[PaginatedData[Dict[str, Any]]],
    summary="Danh sách chuỗi OCR chưa khớp catalog (Phân trang)",
    description="Xem các chuỗi ký tự nhận diện từ vỉ thuốc mà người dùng quét nhưng chưa có trong catalog."
)
def list_unmatched_scans(
    admin_da_xem_xet: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user)
):
    items = db.unmatched_scans
    if admin_da_xem_xet is not None:
        items = [s for s in items if s["admin_da_xem_xet"] == admin_da_xem_xet]
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    return ResponseEnvelope(data=PaginatedData(items=items[start:start+page_size], pagination=PaginationMeta(page=page, page_size=page_size, total_items=total, total_pages=pages)))

@router.patch(
    "/admin/unmatched-scans/{id}/resolve",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Đánh dấu đã xem xét chuỗi OCR chưa khớp",
    description="Đánh dấu đã ánh xạ hoặc thêm thuốc mới vào danh mục."
)
def resolve_unmatched_scan(
    id: int,
    req: ResolveUnmatchedScanRequest,
    admin: CurrentUser = Depends(require_admin_user)
):
    item = next((s for s in db.unmatched_scans if s["id"] == id), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "SCAN_NOT_FOUND", "message": "Không tìm thấy chuỗi quét"})
    item["admin_da_xem_xet"] = req.admin_da_xem_xet
    return ResponseEnvelope(data=MessageResponse(message=f"Đã xử lý chuỗi OCR #{id}."))

# --- Rule Change Logs ---
@router.get(
    "/admin/rule-change-logs",
    response_model=ResponseEnvelope[PaginatedData[RuleChangeLogResponse]],
    summary="Tra cứu nhật ký thay đổi luật tương tác & catalog (Phân trang, Rollback Audit)",
    description="Truy vết toàn bộ các thay đổi về ngưỡng liều, cặp tương tác thuốc/thức ăn và cấu hình danh mục y tế."
)
def list_rule_change_logs(
    table_name: Optional[str] = Query(None, description="Tên bảng dữ liệu luật (drug_interactions, drug_foods...)"),
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
    description="Tra cứu vết kiểm toán append-only mọi truy cập vào dữ liệu bệnh nhân của Admin và Người thân, lọc can thiệp khẩn cấp."
)
def search_audit_logs(
    patient_id: Optional[str] = Query(None, description="Lọc theo bệnh nhân"),
    actor_role: Optional[str] = Query(None, description="Lọc theo role: self, family, admin"),
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
    if actor_role:
        items = [l for l in items if l.get("actor_role") == actor_role]
    if from_date:
        items = [l for l in items if l.get("thoi_gian", "") >= from_date]
    if to_date:
        items = [l for l in items if l.get("thoi_gian", "") <= to_date]
    if is_emergency_override is not None:
        items = [l for l in items if l.get("is_emergency_override") == is_emergency_override]
    if review_status:
        items = [l for l in items if l.get("review_status") == review_status]

    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = [AuditLogResponse(**l) for l in items[start:start+page_size]]

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

    # Update target record status
    new_status = "reviewed_valid" if req.decision == "valid" else "reviewed_invalid"
    audit_log["review_status"] = new_status
    audit_log["reviewer_user_id"] = admin.user_id
    audit_log["reviewed_at"] = current_time_iso()
    audit_log["review_note"] = req.review_note

    # If invalid: add compliance flag and compliance notification (DO NOT auto-restore permissions)
    if req.decision == "invalid":
        audit_log.setdefault("compliance_flags", []).append("COMPLIANCE_REVIEW_REQUIRED")
        db.notifications.append({
            "id": len(db.notifications) + 1,
            "user_id": "usr-admin-1",
            "ve_patient_user_id": audit_log.get("patient_user_id", ""),
            "loai": "canh_bao_compliance",
            "noi_dung": f"Cảnh báo tuân thủ: Thao tác can thiệp khẩn cấp #{id} của Admin {audit_log.get('actor_user_id')} bị đánh giá KHÔNG HỢP LỆ bởi {admin.user_id}. Ghi chú: {req.review_note}.",
            "da_doc": False,
            "thoi_gian": current_time_iso()
        })

    # Record independent audit event for the review action itself (Event #1002)
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
    summary="Danh sách yêu cầu xóa dữ liệu cá nhân chờ duyệt (NĐ 356)",
    description="Xem các yêu cầu xóa dữ liệu hoặc rút consent của người dùng."
)
def list_data_deletion_requests(
    trang_thai: Optional[str] = Query(None, description="cho_duyet, da_duyet, tu_choi"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user)
):
    items = db.data_deletion_requests
    if trang_thai:
        items = [r for r in items if r["trang_thai"] == trang_thai]
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
    summary="Xử lý duyệt hoặc từ chối yêu cầu xóa dữ liệu",
    description="Admin phê duyệt hoặc từ chối kèm lý do."
)
def process_data_deletion_request(
    id: int,
    req: ProcessDeletionRequest,
    admin: CurrentUser = Depends(require_admin_user)
):
    r = next((req_item for req_item in db.data_deletion_requests if req_item["id"] == id), None)
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "REQUEST_NOT_FOUND", "message": "Không tìm thấy yêu cầu"})
    
    r["trang_thai"] = "da_duyet" if req.action == "approve" else "tu_choi"
    r["thoi_gian_xu_ly"] = current_time_iso()
    r["ly_do_tu_choi"] = req.ly_do if req.action == "reject" else None

    status_str = "đã phê duyệt" if req.action == "approve" else "đã từ chối"
    return ResponseEnvelope(data=MessageResponse(message=f"Yêu cầu #{id} {status_str} thành công."))

# --- DPIA Records ---
@router.get(
    "/admin/dpia-records",
    response_model=ResponseEnvelope[List[DpiaRecordResponse]],
    summary="Danh sách hồ sơ đánh giá tác động riêng tư (DPIA)",
    description="Hồ sơ luồng dữ liệu nhạy cảm theo quy định bảo vệ dữ liệu."
)
def list_dpia_records(admin: CurrentUser = Depends(require_admin_user)):
    return ResponseEnvelope(data=[DpiaRecordResponse(**d) for d in db.dpia_records])

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
        "ten_luong_du_lieu": req.ten_luong_du_lieu,
        "co_chuyen_du_lieu_xuyen_bien_gioi": req.co_chuyen_du_lieu_xuyen_bien_gioi,
        "trang_thai": req.trang_thai,
        "nguoi_phe_duyet_id": None,
        "ngay_phe_duyet": None
    }
    db.dpia_records.append(new_record)
    return ResponseEnvelope(data=DpiaRecordResponse(**new_record), message="Tạo hồ sơ DPIA thành công")
