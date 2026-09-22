"""Auth & User Profile Schemas."""
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

class SyncProfileRequest(BaseModel):
    ho_ten: str = Field(..., description="Họ và tên người dùng")
    so_dien_thoai: Optional[str] = Field(None, description="Số điện thoại")
    ngay_sinh: Optional[str] = Field(None, description="Ngày sinh YYYY-MM-DD")
    gioi_tinh: Optional[str] = Field(None, description="Giới tính (nam/nu/khac)")

class UpdateProfileRequest(BaseModel):
    ho_ten: Optional[str] = Field(None, description="Họ và tên người dùng")
    so_dien_thoai: Optional[str] = Field(None, description="Số điện thoại")
    che_do_nguoi_cao_tuoi: Optional[bool] = Field(None, description="Bật/tắt giao diện Simple Mode (dễ đọc, tương phản cao)")

class UserResponse(BaseModel):
    id: str = Field(..., description="UUID người dùng")
    ho_ten: str = Field(..., description="Họ và tên")
    ngay_sinh: Optional[str] = Field(None, description="Ngày sinh YYYY-MM-DD")
    gioi_tinh: Optional[str] = Field(None, description="Giới tính")
    so_dien_thoai: Optional[str] = Field(None, description="Số điện thoại")
    che_do_nguoi_cao_tuoi: bool = Field(default=False, description="Tùy chọn Simple Mode của người dùng thiết bị")
    vai_tro_he_thong: Literal["user", "admin"] = Field(default="user", description="Vai trò hệ thống để cấp quyền Admin")
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

