"""Consent & Data Privacy Schemas (Schema v9: ND 356/2025/ND-CP, QA.01, CD9)."""
from typing import Optional, Literal
from pydantic import BaseModel, Field, AliasChoices

ConsentPurpose = Literal["health_data", "family_sharing", "ai_meal"]
ConsentStatus = Literal["dong_y", "thu_hoi"]
DeletionRequestStatus = Literal["cho_duyet", "da_duyet", "tu_choi", "hoan_tat"]

class ConsentStatusResponse(BaseModel):
    consent_type: ConsentPurpose = Field(..., description="Mục đích xử lý dữ liệu: health_data, family_sharing, ai_meal")
    status: ConsentStatus = Field(..., description="Trạng thái hiện tại: dong_y hoặc thu_hoi")
    consented_at: Optional[str] = Field(None, description="Thời điểm chấp thuận gần nhất")
    revoked_at: Optional[str] = Field(None, description="Thời điểm thu hồi (nếu có)")
    document_version: str = Field(default="v1.0", description="Phiên bản văn bản đồng thuận")

class SubmitConsentRequest(BaseModel):
    consent_type: ConsentPurpose = Field(..., validation_alias=AliasChoices("consent_type", "loai_dong_y"), description="Mục đích: health_data, family_sharing, ai_meal")
    status: ConsentStatus = Field(..., validation_alias=AliasChoices("status", "trang_thai"), description="dong_y hoặc thu_hoi")
    document_version: str = Field(default="v1.0", validation_alias=AliasChoices("document_version", "phien_ban_van_ban"), description="Phiên bản điều khoản đồng thuận")

class ConsentRecordResponse(BaseModel):
    id: int = Field(..., description="ID bản ghi đồng thuận")
    user_id: str = Field(..., description="ID người dùng chủ thể dữ liệu")
    consent_type: ConsentPurpose
    status: ConsentStatus
    consented_at: Optional[str] = None
    revoked_at: Optional[str] = None
    document_version: str

class DataDeletionRequestCreate(BaseModel):
    reason: Optional[str] = Field(None, validation_alias=AliasChoices("reason", "ly_do"), description="Lý do yêu cầu xóa dữ liệu cá nhân")

class DataDeletionRequestResponse(BaseModel):
    id: int = Field(..., description="Mã yêu cầu")
    user_id: str = Field(..., description="Chủ tài khoản")
    status: DeletionRequestStatus = Field(..., description="Trạng thái: cho_duyet, da_duyet, tu_choi, hoan_tat")
    requested_at: str = Field(..., description="Thời điểm yêu cầu")
    handled_by_admin_id: Optional[str] = Field(None, description="ID Admin thụ lý")
    handled_at: Optional[str] = Field(None, description="Thời điểm phê duyệt/từ chối")
    rejection_reason: Optional[str] = Field(None, description="Lý do từ chối (nếu có)")
    completed_at: Optional[str] = Field(None, description="Thời điểm Worker hoàn tất thực thi xóa dữ liệu [MỚI in v9]")
    last_error: Optional[str] = Field(None, description="Lỗi gần nhất trong quá trình thực thi xóa [MỚI in v9]")
