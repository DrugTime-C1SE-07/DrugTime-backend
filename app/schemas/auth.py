"""Auth & User Profile Schemas (Schema v9: English naming, tombstone erased_at, OTP-first)."""
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, AliasChoices

class SyncProfileRequest(BaseModel):
    full_name: Optional[str] = Field(None, validation_alias=AliasChoices("full_name", "ho_ten"), description="Họ và tên người dùng")
    phone_number: Optional[str] = Field(None, validation_alias=AliasChoices("phone_number", "so_dien_thoai"), description="Số điện thoại định dạng E.164")
    email: Optional[str] = Field(None, description="Email người dùng")
    date_of_birth: Optional[str] = Field(None, validation_alias=AliasChoices("date_of_birth", "ngay_sinh"), description="Ngày sinh YYYY-MM-DD")
    gender: Optional[str] = Field(None, validation_alias=AliasChoices("gender", "gioi_tinh"), description="Giới tính (nam/nu/khac)")

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = Field(None, validation_alias=AliasChoices("full_name", "ho_ten"), description="Họ và tên người dùng")
    phone_number: Optional[str] = Field(None, validation_alias=AliasChoices("phone_number", "so_dien_thoai"), description="Số điện thoại định dạng E.164")
    email: Optional[str] = Field(None, description="Email người dùng")
    date_of_birth: Optional[str] = Field(None, validation_alias=AliasChoices("date_of_birth", "ngay_sinh"), description="Ngày sinh YYYY-MM-DD")
    gender: Optional[str] = Field(None, validation_alias=AliasChoices("gender", "gioi_tinh"), description="Giới tính")

class UserResponse(BaseModel):
    id: str = Field(..., description="UUID người dùng (khớp auth.users.id)")
    full_name: Optional[str] = Field(None, description="Họ và tên (nullable trước khi hoàn tất hồ sơ hoặc sau khi xóa dữ liệu)")
    date_of_birth: Optional[str] = Field(None, description="Ngày sinh YYYY-MM-DD")
    gender: Optional[str] = Field(None, description="Giới tính")
    phone_number: Optional[str] = Field(None, description="Số điện thoại E.164")
    email: Optional[str] = Field(None, description="Email")
    system_role: Literal["user", "admin"] = Field(default="user", description="Vai trò hệ thống để cấp quyền Admin")
    erased_at: Optional[str] = Field(default=None, description="Thời điểm xóa dữ liệu cá nhân (tombstone) [MỚI in v9]")
    created_at: str = Field(..., description="Thời gian tạo tài khoản")

class DeviceTokenRequest(BaseModel):
    fcm_token: str = Field(..., description="Firebase Cloud Messaging Device Token")
    platform: Literal["android", "ios"] = Field(..., description="Nền tảng thiết bị di động")

class DataExportJobCreate(BaseModel):
    format: Literal["json", "zip"] = Field(default="json", description="Định dạng xuất dữ liệu")

class DataExportJobResponse(BaseModel):
    job_id: str
    status: Literal["pending", "processing", "completed", "failed"] = "pending"
    message: str = "Yêu cầu trích xuất bản sao dữ liệu cá nhân đã được tiếp nhận và xử lý nền."
    estimated_time_seconds: int = 10

class DataExportJobStatusResponse(BaseModel):
    job_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    download_url: Optional[str] = None
    expires_at: Optional[str] = None
    file_size_bytes: Optional[int] = None
    error: Optional[str] = None

class DataExportResponse(BaseModel):
    user_id: str = Field(..., description="ID người dùng")
    exported_at: str = Field(..., description="Thời gian trích xuất dữ liệu")
    profile: Dict[str, Any] = Field(..., description="Hồ sơ cá nhân")
    conditions: list = Field(default_factory=list, description="Danh sách bệnh nền")
    prescriptions: list = Field(default_factory=list, description="Danh sách đơn thuốc & thuốc")
    dose_logs: list = Field(default_factory=list, description="Lịch sử uống thuốc")
    consents: list = Field(default_factory=list, description="Lịch sử đồng thuận xử lý dữ liệu")
