"""Consent & Data Privacy Schemas (ND 356/2025/ND-CP)."""
from typing import Optional, Literal
from pydantic import BaseModel, Field

ConsentPurpose = Literal["health_data", "family_sharing", "ai_meal"]
ConsentStatus = Literal["dong_y", "thu_hoi"]

class ConsentStatusResponse(BaseModel):
    loai_dong_y: ConsentPurpose = Field(..., description="Mục đích xử lý dữ liệu")
    trang_thai: ConsentStatus = Field(..., description="Trạng thái hiện tại: dong_y hoặc thu_hoi")
    thoi_gian_dong_y: Optional[str] = Field(None, description="Thời điểm chấp thuận gần nhất")
    thoi_gian_thu_hoi: Optional[str] = Field(None, description="Thời điểm thu hồi (nếu có)")
    phien_ban_van_ban: str = Field(default="v1.0", description="Phiên bản văn bản đồng thuận")

class SubmitConsentRequest(BaseModel):
    loai_dong_y: ConsentPurpose = Field(..., description="Mục đích đồng thuận: health_data, family_sharing, ai_meal")
    trang_thai: ConsentStatus = Field(..., description="dong_y hoặc thu_hoi")
    phien_ban_van_ban: str = Field(default="v1.0", description="Phiên bản điều khoản đồng thuận")

class ConsentRecordResponse(BaseModel):
    id: int = Field(..., description="ID bản ghi đồng thuận")
    user_id: str = Field(..., description="ID người dùng chủ thể dữ liệu")
    loai_dong_y: ConsentPurpose = Field(...)
    trang_thai: ConsentStatus = Field(...)
    thoi_gian_dong_y: Optional[str] = None
    thoi_gian_thu_hoi: Optional[str] = None
    phien_ban_van_ban: str

class DataDeletionRequestCreate(BaseModel):
    loai: Literal["xoa_du_lieu", "rut_consent"] = Field(..., description="Loại yêu cầu: xóa toàn bộ dữ liệu hoặc rút consent")
    loai_dong_y: Optional[ConsentPurpose] = Field(None, description="Mục đích rút consent (khi loai = 'rut_consent')")
    ly_do: Optional[str] = Field(None, description="Lý do yêu cầu xóa dữ liệu")

class DataDeletionRequestResponse(BaseModel):
    id: int = Field(..., description="Mã yêu cầu")
    user_id: str = Field(..., description="Chủ tài khoản")
    loai: Literal["xoa_du_lieu", "rut_consent"]
    loai_dong_y: Optional[str] = None
    trang_thai: Literal["cho_duyet", "da_duyet", "tu_choi", "hoan_tat"]
    thoi_gian_yeu_cau: str
    thoi_gian_xu_ly: Optional[str] = None
    ly_do_tu_choi: Optional[str] = None
