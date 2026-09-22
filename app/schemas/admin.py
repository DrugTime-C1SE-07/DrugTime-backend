"""Admin Portal & Compliance Operations Schemas."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from app.schemas.common import PaginationMeta

class AdminMedicationCreate(BaseModel):
    ten_thuoc: str
    hoat_chat_raw: Optional[str] = None
    ham_luong: Optional[str] = None
    dang_bao_che: Optional[str] = None
    cty_san_xuat_ten: Optional[str] = None
    cty_san_xuat_nuoc: Optional[str] = None
    quy_cach_dong_goi: Optional[str] = None
    active_ingredient_ids: List[int] = Field(default_factory=list)

class AdminMedicationUpdate(BaseModel):
    ten_thuoc: Optional[str] = None
    hoat_chat_raw: Optional[str] = None
    ham_luong: Optional[str] = None
    dang_bao_che: Optional[str] = None

class SyncTriggerResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running"]
    source: str = "Cục Quản lý Dược Việt Nam (QĐ 5948/QĐ-BYT)"
    message: str = "Tiến trình đồng bộ danh mục dược phẩm nền đã được kích hoạt"

class SyncStatusResponse(BaseModel):
    job_id: str
    status: Literal["running", "completed", "failed"]
    records_processed: int
    records_updated: int
    last_synced_at: str
    error: Optional[str] = None

class ResolveUnmatchedScanRequest(BaseModel):
    admin_da_xem_xet: bool = True
    mapped_medication_id: Optional[int] = Field(None, description="Ánh xạ sang thuốc có sẵn trong catalog (nếu có)")
    ghi_chu: Optional[str] = None

class AuditLogResponse(BaseModel):
    id: int
    actor_user_id: str
    actor_role: Literal["self", "family", "admin"]
    patient_user_id: str
    data_scope: Literal["ho_so_suc_khoe", "danh_sach_thuoc", "lich_su_tuan_thu", "canh_bao_tuong_tac", "goi_y_bua_an", "admin"]
    ket_qua: Literal["allowed", "denied"]
    ly_do_tu_choi: Optional[str] = None
    ly_do_can_thiep: Optional[str] = None
    action: Optional[str] = None
    is_emergency_override: bool = False
    review_status: Optional[str] = None
    review_deadline: Optional[str] = None
    reviewer_user_id: Optional[str] = None
    target_audit_log_id: Optional[int] = None
    review_decision: Optional[str] = None
    review_note: Optional[str] = None
    compliance_flags: List[str] = Field(default_factory=list)
    thoi_gian: str

class AuditPostReviewRequest(BaseModel):
    decision: Literal["valid", "invalid"]
    review_note: str = Field(..., min_length=10, max_length=2000, description="Ghi chú hậu kiểm (10-2000 ký tự)")

class AuditPostReviewData(BaseModel):
    review_status: Literal["reviewed_valid", "reviewed_invalid"]

class RuleChangeLogResponse(BaseModel):
    id: int
    table_name: str
    record_id: int
    action: Literal["INSERT", "UPDATE", "DELETE"]
    old_data: Optional[dict] = None
    new_data: Optional[dict] = None
    changed_by: str
    changed_at: str
    reason: Optional[str] = None

class ProcessDeletionRequest(BaseModel):
    action: Literal["approve", "reject"] = Field(..., description="approve để phê duyệt xóa hoặc reject để từ chối")
    ly_do: Optional[str] = Field(None, description="Lý do từ chối hoặc ghi chú xử lý")

class DpiaRecordResponse(BaseModel):
    id: int
    ten_luong_du_lieu: str
    co_chuyen_du_lieu_xuyen_bien_gioi: bool
    trang_thai: Literal["ban_nhap", "dang_xem_xet", "da_phe_duyet"]
    nguoi_phe_duyet_id: Optional[str] = None
    ngay_phe_duyet: Optional[str] = None

class DpiaRecordCreate(BaseModel):
    ten_luong_du_lieu: str
    co_chuyen_du_lieu_xuyen_bien_gioi: bool = False
    trang_thai: Literal["ban_nhap", "dang_xem_xet", "da_phe_duyet"] = "ban_nhap"

