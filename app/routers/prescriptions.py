"""Router 4: Prescriptions & Medications."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, UploadFile, File, Header, status, HTTPException
from app.schemas.common import ResponseEnvelope, MessageResponse
from app.schemas.prescriptions import (
    MedicationCatalogResponse, MedicationDetailResponse, UnmatchedScanCreate, UnmatchedScanResponse,
    OcrUploadResponse, PrescriptionCreate, PrescriptionUpdateMetadata, PrescriptionUpdateStatus,
    PrescriptionResponse, UserMedicationCreate, UserMedicationUpdate, UserMedicationResponse
)
from app.core.security import CurrentUser, get_current_user
from app.core.access_control import require_patient_read, require_patient_write, verify_access
from app.mock_db import db, current_time_iso

router = APIRouter(prefix="", tags=["4. Prescriptions & Medications"])

def _trigger_automatic_regimen_analysis(patient_id: str):
    """
    # TODO: implement real logic
    Auto-triggers interaction safety re-analysis whenever medications change.
    """
    pass

@router.get(
    "/medications/search",
    response_model=ResponseEnvelope[List[MedicationCatalogResponse]],
    summary="Tìm kiếm thuốc trong danh mục quốc gia",
    description="Tìm kiếm nhanh thuốc theo tên thương phẩm hoặc hoạt chất (hỗ trợ nhập tay hoặc đối chiếu sau OCR)."
)
def search_medications(
    q: Optional[str] = Query(None, description="Tên thuốc hoặc hoạt chất"),
    limit: int = Query(20, ge=1, le=100)
):
    items = db.medications
    if q:
        items = [m for m in items if q.lower() in m["ten_thuoc"].lower() or (m.get("hoat_chat_raw") and q.lower() in m["hoat_chat_raw"].lower())]
    return ResponseEnvelope(data=[MedicationCatalogResponse(**m) for m in items[:limit]])

@router.get(
    "/medications/{id}",
    response_model=ResponseEnvelope[MedicationDetailResponse],
    summary="Xem chi tiết thuốc và hoạt chất chuẩn hóa (Bảng A)",
    description="Trả về thông tin chi tiết thuốc kèm cấu trúc các hoạt chất Bảng A phục vụ tính liều."
)
def get_medication_detail(id: int):
    med = next((m for m in db.medications if m["id"] == id), None)
    if not med:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc trong danh mục"})
    return ResponseEnvelope(data=MedicationDetailResponse(**med))

@router.post(
    "/medications/unmatched-scans",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[UnmatchedScanResponse],
    summary="Ghi nhận chuỗi quét OCR blister không khớp catalog (R-01)",
    description="Lưu vết chuỗi ký tự nhận diện từ ML Kit nhưng không tìm thấy trong danh mục để Admin xem xét."
)
def report_unmatched_scan(req: UnmatchedScanCreate, caller: CurrentUser = Depends(get_current_user)):
    record = {
        "id": len(db.unmatched_scans) + 1,
        "user_id": caller.user_id,
        "chuoi_nhan_dien": req.chuoi_nhan_dien,
        "thoi_gian": current_time_iso(),
        "admin_da_xem_xet": False
    }
    db.unmatched_scans.append(record)
    return ResponseEnvelope(data=UnmatchedScanResponse(**record), message="Đã gửi chuỗi không khớp để Quản trị viên cập nhật catalog")

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
    
    # Read bytes (mock processing) and check size limit (10MB)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "FILE_TOO_LARGE", "message": "Dung lượng file vượt quá giới hạn tối đa 10MB."}
        )
    
    # Mock OCR result
    matched = [MedicationCatalogResponse(**db.medications[0])]
    unmatched = ["DONG TRUNG HA THAO 500"]
    scanned_text = f"Đơn thuốc ngày 21/09/2026: Glucophage 500mg uống 2 lần/ngày. Đông trùng hạ thảo 500."
    
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
        UserMedicationResponse(**m)
        for m in db.user_medications
        if m["don_thuoc_id"] == p["id"] and m.get("trang_thai", "active") == "active"
    ]
    return PrescriptionResponse(
        id=p["id"],
        user_id=p["user_id"],
        nguon_nhap=p["nguon_nhap"],
        ngay_ke_don=p.get("ngay_ke_don"),
        noi_ke_don=p.get("noi_ke_don"),
        trang_thai=p["trang_thai"],
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
    trang_thai: Optional[str] = Query(None, description="Lọc theo dang_dung hoặc da_ket_thuc"),
    actor_role: str = Depends(require_patient_read("danh_sach_thuoc"))
):
    plist = [p for p in db.prescriptions if p["user_id"] == patient_id and p.get("trang_thai") != "archived"]
    if trang_thai:
        plist = [p for p in plist if p["trang_thai"] == trang_thai]
    return ResponseEnvelope(data=[_build_prescription_response(p) for p in plist])

@router.post(
    "/patients/{patient_id}/prescriptions",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[PrescriptionResponse],
    summary="Tạo đơn thuốc mới kèm danh sách thuốc con",
    description="Yêu cầu quyền GHI. Tự động kích hoạt phân tích an toàn thuốc sau khi thêm."
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
        "nguon_nhap": req.nguon_nhap,
        "ngay_ke_don": req.ngay_ke_don,
        "noi_ke_don": req.noi_ke_don,
        "trang_thai": "dang_dung"
    }
    db.prescriptions.append(new_p)

    for m in req.medications:
        med_catalog = next((cat for cat in db.medications if cat["id"] == m.medication_id), None) if m.medication_id else None
        ten_thuoc = med_catalog["ten_thuoc"] if med_catalog else (m.ten_thuoc_tu_nhap or "Thuốc không rõ tên")
        new_med = {
            "id": len(db.user_medications) + 1,
            "user_id": patient_id,
            "don_thuoc_id": p_id,
            "medication_id": m.medication_id,
            "ten_thuoc": ten_thuoc,
            "cach_nhap": m.cach_nhap,
            "trang_thai_xac_nhan": "da_xac_nhan",
            "so_luong_moi_lan": m.so_luong_moi_lan,
            "so_lan_moi_ngay": m.so_lan_moi_ngay,
            "don_vi_uong": m.don_vi_uong or "viên",
            "co_du_lieu_tuong_tac": True,
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
    if not p or p.get("trang_thai") == "archived":
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
    if not p or p.get("trang_thai") == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PRESCRIPTION_NOT_FOUND", "message": "Không tìm thấy đơn thuốc"})
    
    verify_access(caller, p["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    if req.ngay_ke_don is not None:
        p["ngay_ke_don"] = req.ngay_ke_don
    if req.noi_ke_don is not None:
        p["noi_ke_don"] = req.noi_ke_don

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
    p["trang_thai"] = req.trang_thai
    
    _trigger_automatic_regimen_analysis(p["user_id"])
    return ResponseEnvelope(data=_build_prescription_response(p), message=f"Đã cập nhật trạng thái đơn thuốc thành {req.trang_thai}")

@router.post(
    "/prescriptions/{id}/medications",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[UserMedicationResponse],
    summary="Thêm thuốc lẻ vào đơn thuốc hiện có",
    description="Yêu cầu quyền GHI. Tự động kích hoạt phân tích an toàn thuốc."
)
def add_medication_to_prescription(
    id: int,
    req: UserMedicationCreate,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    p = next((p for p in db.prescriptions if p["id"] == id), None)
    if not p or p.get("trang_thai") == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "PRESCRIPTION_NOT_FOUND", "message": "Không tìm thấy đơn thuốc"})
    
    verify_access(caller, p["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    
    med_catalog = next((cat for cat in db.medications if cat["id"] == req.medication_id), None) if req.medication_id else None
    ten_thuoc = med_catalog["ten_thuoc"] if med_catalog else (req.ten_thuoc_tu_nhap or "Thuốc tự nhập")

    new_med = {
        "id": len(db.user_medications) + 1,
        "user_id": p["user_id"],
        "don_thuoc_id": id,
        "medication_id": req.medication_id,
        "ten_thuoc": ten_thuoc,
        "cach_nhap": req.cach_nhap,
        "trang_thai_xac_nhan": "da_xac_nhan",
        "so_luong_moi_lan": req.so_luong_moi_lan,
        "so_lan_moi_ngay": req.so_lan_moi_ngay,
        "don_vi_uong": req.don_vi_uong or "viên",
        "co_du_lieu_tuong_tac": True,
        "trang_thai": "active"
    }
    db.user_medications.append(new_med)
    _trigger_automatic_regimen_analysis(p["user_id"])

    return ResponseEnvelope(data=UserMedicationResponse(**new_med), message="Thêm thuốc vào đơn thành công")

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
    if not med or med.get("trang_thai") == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc trong đơn"})
    
    verify_access(caller, med["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    if req.so_luong_moi_lan is not None:
        med["so_luong_moi_lan"] = req.so_luong_moi_lan
    if req.so_lan_moi_ngay is not None:
        med["so_lan_moi_ngay"] = req.so_lan_moi_ngay
    if req.trang_thai_xac_nhan is not None:
        med["trang_thai_xac_nhan"] = req.trang_thai_xac_nhan

    _trigger_automatic_regimen_analysis(med["user_id"])
    return ResponseEnvelope(data=UserMedicationResponse(**med), message="Cập nhật liều lượng thuốc thành công")

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
    if not med or med.get("trang_thai") == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc"})
    
    verify_access(caller, med["user_id"], required_permission="write", data_scope="danh_sach_thuoc", admin_reason=x_admin_reason)
    med["trang_thai"] = "archived"
    
    _trigger_automatic_regimen_analysis(med["user_id"])
    return ResponseEnvelope(data=MessageResponse(message=f"Đã lưu trữ thuốc '{med['ten_thuoc']}' thành công"))
