"""Admin Portal & Compliance Operations Schemas (Schema v9)."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, AliasChoices

class AdminMedicationCreate(BaseModel):
    name: str = Field(..., validation_alias=AliasChoices("name", "ten_thuoc"))
    raw_active_ingredient: Optional[str] = Field(None, validation_alias=AliasChoices("raw_active_ingredient", "hoat_chat_raw"))
    strength_text: Optional[str] = Field(None, validation_alias=AliasChoices("strength_text", "ham_luong"))
    dosage_form: Optional[str] = Field(None, validation_alias=AliasChoices("dosage_form", "dang_bao_che"))
    manufacturer_name: Optional[str] = Field(None, validation_alias=AliasChoices("manufacturer_name", "cty_san_xuat_ten"))
    manufacturer_country: Optional[str] = Field(None, validation_alias=AliasChoices("manufacturer_country", "cty_san_xuat_nuoc"))
    packaging_spec: Optional[str] = Field(None, validation_alias=AliasChoices("packaging_spec", "quy_cach_dong_goi"))
    active_ingredient_ids: List[int] = Field(default_factory=list)

class AdminMedicationUpdate(BaseModel):
    name: Optional[str] = Field(None, validation_alias=AliasChoices("name", "ten_thuoc"))
    raw_active_ingredient: Optional[str] = Field(None, validation_alias=AliasChoices("raw_active_ingredient", "hoat_chat_raw"))
    strength_text: Optional[str] = Field(None, validation_alias=AliasChoices("strength_text", "ham_luong"))
    dosage_form: Optional[str] = Field(None, validation_alias=AliasChoices("dosage_form", "dang_bao_che"))
    manufacturer_name: Optional[str] = Field(None, validation_alias=AliasChoices("manufacturer_name", "cty_san_xuat_ten"))
    manufacturer_country: Optional[str] = Field(None, validation_alias=AliasChoices("manufacturer_country", "cty_san_xuat_nuoc"))
    packaging_spec: Optional[str] = Field(None, validation_alias=AliasChoices("packaging_spec", "quy_cach_dong_goi"))

class SyncTriggerResponse(BaseModel):
    job_id: str
    status: Literal["dang_chay", "thanh_cong", "that_bai"]
    source: Literal["dav_drugbank", "qd_5948", "duoc_thu_qg"] = "qd_5948"
    message: str = "Tiến trình đồng bộ danh mục dược phẩm đã được kích hoạt"

class SyncStatusResponse(BaseModel):
    id: int
    source: Literal["dav_drugbank", "qd_5948", "duoc_thu_qg"]
    started_at: str
    finished_at: Optional[str] = None
    status: Literal["dang_chay", "thanh_cong", "that_bai"]
    records_inserted: int = 0
    records_updated: int = 0
    records_failed: int = 0
    error_details: Optional[str] = None
    triggered_by: Literal["scheduler", "admin_thu_cong"] = "admin_thu_cong"

class AuditLogResponse(BaseModel):
    id: int
    actor_user_id: str
    actor_role: Literal["family", "admin", "khong_co_quyen"] = Field(..., description="Role ngữ cảnh: family, admin, khong_co_quyen (không có self theo Schema v9)")
    patient_user_id: str
    data_scope: Literal["ho_so_suc_khoe", "danh_sach_thuoc", "lich_su_tuan_thu", "canh_bao_tuong_tac", "goi_y_bua_an", "admin"]
    result: Literal["allowed", "denied"]
    rejection_reason: Optional[str] = None
    override_reason: Optional[str] = None
    action: Optional[str] = None
    is_emergency_override: bool = False
    review_status: Optional[str] = None
    review_deadline: Optional[str] = None
    reviewer_user_id: Optional[str] = None
    target_audit_log_id: Optional[int] = None
    review_decision: Optional[str] = None
    review_note: Optional[str] = None
    compliance_flags: List[str] = Field(default_factory=list)
    accessed_at: str

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
    rejection_reason: Optional[str] = Field(None, validation_alias=AliasChoices("rejection_reason", "ly_do"), description="Lý do từ chối hoặc ghi chú xử lý")

class DpiaRecordResponse(BaseModel):
    id: int
    data_flow_name: str
    has_cross_border_transfer: bool
    status: Literal["ban_nhap", "dang_xem_xet", "da_phe_duyet"]
    approved_by_id: Optional[str] = None
    approval_date: Optional[str] = None

class DpiaRecordCreate(BaseModel):
    data_flow_name: str = Field(..., validation_alias=AliasChoices("data_flow_name", "ten_luong_du_lieu"))
    has_cross_border_transfer: bool = Field(default=False, validation_alias=AliasChoices("has_cross_border_transfer", "co_chuyen_du_lieu_xuyen_bien_gioi"))
    status: Literal["ban_nhap", "dang_xem_xet", "da_phe_duyet"] = Field(default="ban_nhap", validation_alias=AliasChoices("status", "trang_thai"))
