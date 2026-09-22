"""Caregiver & Family Linking Schemas."""
from typing import Optional, Literal
from pydantic import BaseModel, Field

CaregiverStatus = Literal["pending", "active", "revoked"]

class LinkCodeResponse(BaseModel):
    ma: str = Field(..., description="Mã 6 ký tự hoặc URL sinh QR code")
    het_han_luc: str = Field(..., description="Thời gian hết hạn ISO 8601 (15 phút)")
    patient_name: str = Field(..., description="Tên bệnh nhân tạo mã")

class RedeemLinkCodeRequest(BaseModel):
    ma: str = Field(..., min_length=4, max_length=10, description="Mã liên kết do bệnh nhân cung cấp")

class CaregiverLinkResponse(BaseModel):
    id: int = Field(...)
    patient_user_id: str = Field(...)
    patient_name: Optional[str] = None
    family_user_id: str = Field(...)
    family_name: Optional[str] = None
    trang_thai: CaregiverStatus = Field(..., description="pending, active, hoặc revoked")
    cho_phep_chia_se: bool = Field(..., description="Quyền ĐỌC (xem danh sách thuốc, lịch sử tuân thủ)")
    cho_phep_chinh_sua: bool = Field(default=False, description="Quyền GHI (sửa lịch, thêm thuốc hộ người cao tuổi)")
    thoi_gian_lien_ket: str
    thoi_gian_thu_hoi: Optional[str] = None

class CaregiverLinkUpdateRequest(BaseModel):
    cho_phep_chia_se: Optional[bool] = Field(None, description="Bật/tắt quyền xem dữ liệu")
    cho_phep_chinh_sua: Optional[bool] = Field(None, description="Bật/tắt quyền thao tác ghi hộ")
    trang_thai: Optional[Literal["active", "revoked"]] = Field(None, description="Thu hồi liên kết (revoked)")

class MonitoredPatientResponse(BaseModel):
    patient_id: str = Field(..., description="ID bệnh nhân đang theo dõi")
    ho_ten: str = Field(..., description="Họ tên bệnh nhân")
    link_id: int = Field(...)
    cho_phep_chia_se: bool
    cho_phep_chinh_sua: bool
    today_adherence_percent: float = Field(..., description="Tỷ lệ tuân thủ thuốc hôm nay (0-100%)")
    today_missed_count: int = Field(..., description="Số liều đã bị bỏ lỡ trong ngày")

class NotificationResponse(BaseModel):
    id: int
    user_id: str
    ve_patient_user_id: str
    loai: Literal["nhac_uong_thuoc", "canh_bao_bo_lo_lieu_nguoi_than", "canh_bao_admin_override", "canh_bao_compliance"]
    noi_dung: str
    da_doc: bool
    thoi_gian: str

