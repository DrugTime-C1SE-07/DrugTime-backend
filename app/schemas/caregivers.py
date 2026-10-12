"""Caregiver & Family Linking Schemas (Schema v9: English naming, sharing_enabled, dedupe_key)."""
from typing import Optional, Literal
from pydantic import BaseModel, Field, AliasChoices

CaregiverStatus = Literal["pending", "active", "revoked"]

class LinkCodeResponse(BaseModel):
    code: str = Field(..., description="Mã 6 ký tự hoặc URL sinh QR code")
    expires_at: str = Field(..., description="Thời gian hết hạn ISO 8601 (15 phút)")
    patient_name: str = Field(..., description="Tên bệnh nhân tạo mã")

class RedeemLinkCodeRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=10, validation_alias=AliasChoices("code", "ma"), description="Mã liên kết do bệnh nhân cung cấp")

class CaregiverLinkResponse(BaseModel):
    id: int = Field(...)
    patient_user_id: str = Field(...)
    patient_name: Optional[str] = None
    family_user_id: str = Field(...)
    family_name: Optional[str] = None
    status: CaregiverStatus = Field(..., description="pending, active, hoặc revoked")
    sharing_enabled: bool = Field(..., description="Công tắc chia sẻ dữ liệu do bệnh nhân điều khiển")
    linked_at: str
    revoked_at: Optional[str] = None

class CaregiverLinkUpdateRequest(BaseModel):
    sharing_enabled: Optional[bool] = Field(None, validation_alias=AliasChoices("sharing_enabled", "cho_phep_chia_se"), description="Bật/tắt quyền xem dữ liệu")
    status: Optional[Literal["active", "revoked"]] = Field(None, validation_alias=AliasChoices("status", "trang_thai"), description="Thu hồi liên kết (revoked)")
    can_edit: Optional[bool] = Field(None, validation_alias=AliasChoices("can_edit", "cho_phep_chinh_sua"), description="Quyền chỉnh sửa (chỉ bệnh nhân được cấp)")

class MonitoredPatientResponse(BaseModel):
    patient_id: str = Field(..., description="ID bệnh nhân đang theo dõi")
    full_name: str = Field(..., description="Họ tên bệnh nhân")
    link_id: int = Field(...)
    sharing_enabled: bool
    today_adherence_percent: float = Field(..., description="Tỷ lệ tuân thủ thuốc hôm nay (0-100%)")
    today_missed_count: int = Field(..., description="Số liều đã bị bỏ lỡ trong ngày")

class NotificationResponse(BaseModel):
    id: int
    user_id: str
    about_patient_user_id: str = Field(..., description="Thông báo nói về bệnh nhân nào")
    type: Literal["nhac_uong_thuoc", "canh_bao_bo_lo_lieu_nguoi_than", "canh_bao_admin_override", "canh_bao_compliance"]
    content: str = Field(..., description="Nội dung chi tiết (chỉ đọc qua API, không đưa vào push)")
    is_read: bool
    dedupe_key: Optional[str] = Field(None, description="Khóa chống trùng cảnh báo [MỚI in v9]")
    created_at: str = Field(..., description="Thời điểm tạo thông báo [MỚI in v9]")
