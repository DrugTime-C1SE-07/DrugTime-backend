"""Router 4: Prescriptions & Medications (Schema v9: English naming, no free text, no unmatched_scans)."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, UploadFile, File, Header, status, HTTPException
from app.schemas.common import ResponseEnvelope, MessageResponse
from app.schemas.prescriptions import (
    MedicationCatalogResponse, MedicationDetailResponse,
    OcrUploadResponse, PrescriptionCreate, PrescriptionUpdateMetadata, PrescriptionUpdateStatus,
    PrescriptionResponse, UserMedicationCreate, UserMedicationUpdate, UserMedicationResponse
)
from app.core.security import CurrentUser, get_current_user
from app.core.access_control import require_patient_read, require_patient_write, verify_access
from app.mock_db import db, current_time_iso

router = APIRouter(prefix="", tags=["4. Prescriptions & Medications"])

def _trigger_automatic_regimen_analysis(patient_id: str):
    """
    Auto-triggers interaction safety re-analysis whenever medications change.
    """
    pass

@router.get(
    "/medications/search",
    response_model=ResponseEnvelope[List[MedicationCatalogResponse]],
    summary="Tìm kiếm thuốc trong danh mục quốc gia",
    description="Tìm kiếm nhanh thuốc theo tên thương phẩm hoặc hoạt chất (Schema v9: lọc deleted_at IS NULL)."
)
def search_medications(
    q: Optional[str] = Query(None, description="Tên thuốc hoặc hoạt chất"),
    limit: int = Query(20, ge=1, le=100)
):
    items = [m for m in db.medications if m.get("deleted_at") is None]
    if q:
        items = [
            m for m in items
            if q.lower() in m.get("name", m.get("ten_thuoc", "")).lower()
            or (m.get("raw_active_ingredient") and q.lower() in m["raw_active_ingredient"].lower())
            or (m.get("hoat_chat_raw") and q.lower() in m["hoat_chat_raw"].lower())
        ]
    formatted = [
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
        for m in items[:limit]
    ]
    return ResponseEnvelope(data=formatted)

@router.get(
    "/medications/{id}",
    response_model=ResponseEnvelope[MedicationDetailResponse],
    summary="Xem chi tiết thuốc và hoạt chất chuẩn hóa (Bảng A)",
    description="Trả về thông tin chi tiết thuốc kèm cấu trúc các hoạt chất Bảng A phục vụ tính liều."
)
def get_medication_detail(id: int):
    med = next((m for m in db.medications if m["id"] == id and m.get("deleted_at") is None), None)
    if not med:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc trong danh mục"})
    
    ingredients = [
        {
            "id": ing["id"],
            "standard_name": ing.get("standard_name", ing.get("ten_hoat_chat_chuan")),
            "strength_value": ing.get("strength_value", ing.get("ham_luong_value")),
            "strength_unit": ing.get("strength_unit", ing.get("ham_luong_unit")),
            "dosing_unit": ing.get("dosing_unit", ing.get("don_vi_dinh_luong"))
        }
        for ing in med.get("active_ingredients", [])
    ]
    
    return ResponseEnvelope(data=MedicationDetailResponse(
        id=med["id"],
        name=med.get("name", med.get("ten_thuoc")),
        raw_active_ingredient=med.get("raw_active_ingredient", med.get("hoat_chat_raw")),
        strength_text=med.get("strength_text", med.get("ham_luong")),
        dosage_form=med.get("dosage_form", med.get("dang_bao_che")),
        manufacturer_name=med.get("manufacturer_name", med.get("cty_san_xuat_ten")),
        manufacturer_country=med.get("manufacturer_country", med.get("cty_san_xuat_nuoc")),
        packaging_spec=med.get("packaging_spec", med.get("quy_cach_dong_goi")),
        deleted_at=med.get("deleted_at"),
        active_ingredients=ingredients
    ))

@router.post(
    "/patients/{patient_id}/prescriptions/ocr-upload",
    response_model=ResponseEnvelope[OcrUploadResponse],
    summary="Upload ảnh/PDF vỉ thuốc hoặc đơn thuốc nhận diện OCR preview (Max 10MB, Quyền READ)",
    description="Nhận file ảnh JPG, PNG, WEBP hoặc PDF (tối đa 10MB) để trích xuất text xem trước (không ghi rác DB). Yêu cầu quyền READ."
)
async def upload_prescription_ocr(
    patient_id: str,
    file: UploadFile = File(..., description="File ảnh vỉ thuốc hoặc file PDF đơn thuốc"),
    actor_role: str = Depends(require_patient_read("danh_sach_thuoc"))
):
    allowed_types = {"image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"}
    if file.content_type and file.content_type.lower() not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_FILE_TYPE", "message": "Chỉ chấp nhận file định dạng JPG, PNG, WEBP hoặc PDF."}
        )
    
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "FILE_TOO_LARGE", "message": "Dung lượng file vượt quá giới hạn tối đa 10MB."}
        )
    
    matched = [
        MedicationCatalogResponse(
            id=db.medications[0]["id"],
            name=db.medications[0].get("name", db.medications[0].get("ten_thuoc")),
            raw_active_ingredient=db.medications[0].get("raw_active_ingredient", db.medications[0].get("hoat_chat_raw")),
            strength_text=db.medications[0].get("strength_text", db.medications[0].get("ham_luong")),
            dosage_form=db.medications[0].get("dosage_form", db.medications[0].get("dang_bao_che")),
            manufacturer_name=db.medications[0].get("manufacturer_name", db.medications[0].get("cty_san_xuat_ten")),
            manufacturer_country=db.medications[0].get("manufacturer_country", db.medications[0].get("cty_san_xuat_nuoc")),
            packaging_spec=db.medications[0].get("packaging_spec", db.medications[0].get("quy_cach_dong_goi")),
            deleted_at=db.medications[0].get("deleted_at")
        )
    ]
    unmatched = ["DONG TRUNG HA THAO 500"]
    scanned_text = "Đơn thuốc ngày 21/09/2026: Glucophage 500mg uống 2 lần/ngày. Đông trùng hạ thảo 500."
    
    return ResponseEnvelope(
        data=OcrUploadResponse(
            scanned_text=scanned_text,
            matched_medications=matched,
            unmatched_lines=unmatched
        ),
        message="Nhận diện ảnh thành công. Vui lòng xác nhận danh sách thuốc trước khi lưu."
    )

def _build_prescription_response(p: dict) -> PrescriptionResponse:
    user_meds = [
        UserMedicationResponse(
            id=m["id"],
            user_id=m["user_id"],
            prescription_id=m.get("prescription_id", m.get("don_thuoc_id")),
            medication_id=m["medication_id"],
            name=m.get("name", m.get("ten_thuoc")),
            entry_method=m.get("entry_method", m.get("cach_nhap")),
            confirmation_status=m.get("confirmation_status", m.get("trang_thai_xac_nhan")),
            quantity_per_dose=m.get("quantity_per_dose", m.get("so_luong_moi_lan")),
            doses_per_day=m.get("doses_per_day", m.get("so_lan_moi_ngay")),
            dosing_unit=m.get("dosing_unit", m.get("don_vi_uong", "viên")),
            has_interaction_data=m.get("has_interaction_data", m.get("co_du_lieu_tuong_tac", True)),
            status=m.get("status", m.get("trang_thai", "active"))
        )
        for m in db.user_medications
        if m.get("prescription_id", m.get("don_thuoc_id")) == p["id"] and m.get("status", m.get("trang_thai", "active")) == "active"
    ]
    return PrescriptionResponse(
        id=p["id"],
        user_id=p["user_id"],
        entry_source=p.get("entry_source", p.get("nguon_nhap")),
        prescribed_date=p.get("prescribed_date", p.get("ngay_ke_don")),
        prescribing_facility=p.get("prescribing_facility", p.get("noi_ke_don")),
        status=p.get("status", p.get("trang_thai")),
        medications=user_meds
    )

@router.get(
    "/patients/{patient_id}/prescriptions",
    response_model=ResponseEnvelope[List[PrescriptionResponse]],
    summary="Lấy danh sách đơn thuốc của bệnh nhân",
    description="Lọc theo trạng thái dang_dung hoặc da_ket_thuc. Yêu cầu quyền ĐỌC."
)
def get_patient_prescriptions(
    patient_id: str,
    status: Optional[str] = Query(None, alias="status", description="Lọc theo dang_dung hoặc da_ket_thuc"),
    actor_role: str = Depends(require_patient_read("danh_sach_thuoc"))
):
    plist = [
        p for p in db.prescriptions
        if p["user_id"] == patient_id and p.get("status", p.get("trang_thai")) != "archived"
    ]
    if status:
        plist = [p for p in plist if p.get("status", p.get("trang_thai")) == status]
    return ResponseEnvelope(data=[_build_prescription_response(p) for p in plist])

@router.post(
    "/patients/{patient_id}/prescriptions",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[PrescriptionResponse],
    summary="Tạo đơn thuốc mới kèm danh sách thuốc con",
    description="Yêu cầu quyền GHI. Thuốc con bắt buộc chọn từ danh mục (không nhập tự do theo Schema v5-v9). Tự động kích hoạt phân tích an toàn thuốc sau khi thêm."
)
def create_prescription(
    patient_id: str,
    req: PrescriptionCreate,
    actor_role: str = Depends(require_patient_write("danh_sach_thuoc"))
):
    p_id = len(db.prescriptions) + 1
    new_p = {
        "id": p_id,
        "user_id": patient_id,
        "entry_source": req.entry_source,
        "nguon_nhap": req.entry_source,
        "prescribed_date": req.prescribed_date,
        "ngay_ke_don": req.prescribed_date,
        "prescribing_facility": req.prescribing_facility,
        "noi_ke_don": req.prescribing_facility,
        "status": "dang_dung",
        "trang_thai": "dang_dung"
    }
    db.prescriptions.append(new_p)

    for m in req.medications:
        med_catalog = next((cat for cat in db.medications if cat["id"] == m.medication_id), None)
        if not med_catalog:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "MEDICATION_NOT_FOUND", "message": f"Không tìm thấy thuốc ID #{m.medication_id} trong danh mục"}
            )
        med_name = med_catalog.get("name", med_catalog.get("ten_thuoc"))
        new_med = {
            "id": len(db.user_medications) + 1,
            "user_id": patient_id,
            "prescription_id": p_id,
            "don_thuoc_id": p_id,
            "medication_id": m.medication_id,
            "name": med_name,
            "ten_thuoc": med_name,
            "entry_method": m.entry_method,
            "cach_nhap": m.entry_method,
            "confirmation_status": "da_xac_nhan",
            "trang_thai_xac_nhan": "da_xac_nhan",
            "quantity_per_dose": m.quantity_per_dose,
            "so_luong_moi_lan": m.quantity_per_dose,
            "doses_per_day": m.doses_per_day,
            "so_lan_moi_ngay": m.doses_per_day,
            "dosing_unit": m.dosing_unit or "viên",
            "don_vi_uong": m.dosing_unit or "viên",
            "has_interaction_data": True,
            "co_du_lieu_tuong_tac": True,
            "status": "active",
            "trang_thai": "active"
        }
        db.user_medications.append(new_med)

    _trigger_automatic_regimen_analysis(patient_id)
    return ResponseEnvelope(data=_build_prescription_response(new_p), message="Tạo đơn thuốc thành công và đã chạy phân tích tương tác")

@router.get(
    "/prescriptions/{id}",
    response_model=ResponseEnvelope[PrescriptionResponse],
    summary="Chi tiết một đơn thuốc",
    description="Yêu cầu quyền ĐỌC dữ liệu của chủ đơn thuốc."
)
def get_prescription_detail(id: int, caller: CurrentUser = Depends(get_current_user)):
    p = next((p for p in db.prescriptions if p["id"] == id), None)
    if not p or p.get("status", p.get("trang_thai")) == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PRESCRIPTION_NOT_FOUND", "message": "Không tìm thấy đơn thuốc"})
    
    verify_access(caller, p["user_id"], required_permission="read", data_scope="danh_sach_thuoc")
    return ResponseEnvelope(data=_build_prescription_response(p))

@router.patch(
    "/prescriptions/{id}",
    response_model=ResponseEnvelope[PrescriptionResponse],
    summary="Chỉnh sửa metadata đơn thuốc (ngày kê, nơi kê)",
    description="Sửa thông tin sau khi quét OCR sai ngày hoặc nơi kê đơn. Yêu cầu quyền GHI."
)
def update_prescription_metadata(
    id: int,
    req: PrescriptionUpdateMetadata,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    p = next((p for p in db.prescriptions if p["id"] == id), None)
    if not p or p.get("status", p.get("trang_thai")) == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PRESCRIPTION_NOT_FOUND", "message": "Không tìm thấy đơn thuốc"})
    
    verify_access(caller, p["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    if req.prescribed_date is not None:
        p["prescribed_date"] = req.prescribed_date
        p["ngay_ke_don"] = req.prescribed_date
    if req.prescribing_facility is not None:
        p["prescribing_facility"] = req.prescribing_facility
        p["noi_ke_don"] = req.prescribing_facility

    return ResponseEnvelope(data=_build_prescription_response(p), message="Cập nhật thông tin đơn thuốc thành công")

@router.patch(
    "/prescriptions/{id}/status",
    response_model=ResponseEnvelope[PrescriptionResponse],
    summary="Cập nhật trạng thái đơn thuốc (da_ket_thuc / dang_dung)",
    description="Đánh dấu kết thúc đơn thuốc. Tự động loại khỏi phân tích tương tác thuốc đang dùng."
)
def update_prescription_status(
    id: int,
    req: PrescriptionUpdateStatus,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    p = next((p for p in db.prescriptions if p["id"] == id), None)
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PRESCRIPTION_NOT_FOUND", "message": "Không tìm thấy đơn thuốc"})
    
    verify_access(caller, p["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    p["status"] = req.status
    p["trang_thai"] = req.status
    
    _trigger_automatic_regimen_analysis(p["user_id"])
    return ResponseEnvelope(data=_build_prescription_response(p), message=f"Đã cập nhật trạng thái đơn thuốc thành {req.status}")

@router.post(
    "/prescriptions/{id}/medications",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[UserMedicationResponse],
    summary="Thêm thuốc lẻ vào đơn thuốc hiện có",
    description="Yêu cầu quyền GHI. Thuốc bắt buộc có trong catalog. Tự động kích hoạt phân tích an toàn thuốc."
)
def add_medication_to_prescription(
    id: int,
    req: UserMedicationCreate,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    p = next((p for p in db.prescriptions if p["id"] == id), None)
    if not p or p.get("status", p.get("trang_thai")) == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PRESCRIPTION_NOT_FOUND", "message": "Không tìm thấy đơn thuốc"})
    
    verify_access(caller, p["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    
    med_catalog = next((cat for cat in db.medications if cat["id"] == req.medication_id), None)
    if not med_catalog:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "MEDICATION_NOT_FOUND", "message": f"Không tìm thấy thuốc #{req.medication_id} trong danh mục"})
    
    med_name = med_catalog.get("name", med_catalog.get("ten_thuoc"))
    new_med = {
        "id": len(db.user_medications) + 1,
        "user_id": p["user_id"],
        "prescription_id": id,
        "don_thuoc_id": id,
        "medication_id": req.medication_id,
        "name": med_name,
        "ten_thuoc": med_name,
        "entry_method": req.entry_method,
        "cach_nhap": req.entry_method,
        "confirmation_status": "da_xac_nhan",
        "trang_thai_xac_nhan": "da_xac_nhan",
        "quantity_per_dose": req.quantity_per_dose,
        "so_luong_moi_lan": req.quantity_per_dose,
        "doses_per_day": req.doses_per_day,
        "so_lan_moi_ngay": req.doses_per_day,
        "dosing_unit": req.dosing_unit or "viên",
        "don_vi_uong": req.dosing_unit or "viên",
        "has_interaction_data": True,
        "co_du_lieu_tuong_tac": True,
        "status": "active",
        "trang_thai": "active"
    }
    db.user_medications.append(new_med)
    _trigger_automatic_regimen_analysis(p["user_id"])

    return ResponseEnvelope(
        data=UserMedicationResponse(
            id=new_med["id"],
            user_id=new_med["user_id"],
            prescription_id=new_med["prescription_id"],
            medication_id=new_med["medication_id"],
            name=new_med["name"],
            entry_method=new_med["entry_method"],
            confirmation_status=new_med["confirmation_status"],
            quantity_per_dose=new_med["quantity_per_dose"],
            doses_per_day=new_med["doses_per_day"],
            dosing_unit=new_med["dosing_unit"],
            has_interaction_data=new_med["has_interaction_data"],
            status=new_med["status"]
        ),
        message="Thêm thuốc vào đơn thành công"
    )

@router.patch(
    "/user-medications/{id}",
    response_model=ResponseEnvelope[UserMedicationResponse],
    summary="Chỉnh sửa liều lượng thuốc trong đơn",
    description="Sửa số lượng mỗi lần hoặc tần suất số lần uống mỗi ngày. Tự động kích hoạt phân tích liều."
)
def update_user_medication(
    id: int,
    req: UserMedicationUpdate,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    med = next((m for m in db.user_medications if m["id"] == id), None)
    if not med or med.get("status", med.get("trang_thai")) == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc trong đơn"})
    
    verify_access(caller, med["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    if req.quantity_per_dose is not None:
        med["quantity_per_dose"] = req.quantity_per_dose
        med["so_luong_moi_lan"] = req.quantity_per_dose
    if req.doses_per_day is not None:
        med["doses_per_day"] = req.doses_per_day
        med["so_lan_moi_ngay"] = req.doses_per_day
    if req.confirmation_status is not None:
        med["confirmation_status"] = req.confirmation_status
        med["trang_thai_xac_nhan"] = req.confirmation_status

    _trigger_automatic_regimen_analysis(med["user_id"])
    return ResponseEnvelope(
        data=UserMedicationResponse(
            id=med["id"],
            user_id=med["user_id"],
            prescription_id=med.get("prescription_id", med.get("don_thuoc_id")),
            medication_id=med["medication_id"],
            name=med.get("name", med.get("ten_thuoc")),
            entry_method=med.get("entry_method", med.get("cach_nhap")),
            confirmation_status=med.get("confirmation_status", med.get("trang_thai_xac_nhan")),
            quantity_per_dose=med.get("quantity_per_dose", med.get("so_luong_moi_lan")),
            doses_per_day=med.get("doses_per_day", med.get("so_lan_moi_ngay")),
            dosing_unit=med.get("dosing_unit", med.get("don_vi_uong", "viên")),
            has_interaction_data=med.get("has_interaction_data", med.get("co_du_lieu_tuong_tac", True)),
            status=med.get("status", med.get("trang_thai", "active"))
        ),
        message="Cập nhật liều lượng thuốc thành công"
    )

@router.delete(
    "/user-medications/{id}",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Xóa (soft-delete) thuốc khỏi đơn",
    description="Chuyển trạng thái thuốc sang 'archived' để bảo tồn lịch sử điều trị. Tự động re-analyze."
)
def delete_user_medication(
    id: int,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    med = next((m for m in db.user_medications if m["id"] == id), None)
    if not med or med.get("status", med.get("trang_thai")) == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc"})
    
    verify_access(caller, med["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    med["status"] = "archived"
    med["trang_thai"] = "archived"
    
    _trigger_automatic_regimen_analysis(med["user_id"])
    med_name = med.get("name", med.get("ten_thuoc"))
    return ResponseEnvelope(data=MessageResponse(message=f"Đã lưu trữ thuốc '{med_name}' thành công"))
