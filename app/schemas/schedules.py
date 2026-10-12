"""Schedules & Dose Logs Schemas (Schema v9: English naming, effective_from, nullable taken_at/client_uuid)."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, AliasChoices

ScheduleType = Literal["co_dinh", "khi_can"]
DoseStatus = Literal["Đã uống", "Bỏ lỡ", "Uống trễ"]
RecordStatus = Literal["active", "archived"]

class ScheduleCreate(BaseModel):
    intake_time: Optional[str] = Field("08:00", validation_alias=AliasChoices("intake_time", "gio_uong"), description="Giờ uống định dạng HH:MM (Asia/Ho_Chi_Minh)")
    days_of_week: Optional[str] = Field("2,3,4,5,6,7,CN", validation_alias=AliasChoices("days_of_week", "ngay_trong_tuan"), description="Danh sách các thứ trong tuần")
    reminder_enabled: bool = Field(default=True, validation_alias=AliasChoices("reminder_enabled", "bat_tat_nhac"), description="Bật/tắt nhắc nhở cho khung giờ này")
    schedule_type: ScheduleType = Field(default="co_dinh", validation_alias=AliasChoices("schedule_type", "loai_lich"), description="co_dinh hoặc khi_can")

class ScheduleUpdate(BaseModel):
    intake_time: Optional[str] = Field(None, validation_alias=AliasChoices("intake_time", "gio_uong"), description="Sửa giờ uống HH:MM")
    days_of_week: Optional[str] = Field(None, validation_alias=AliasChoices("days_of_week", "ngay_trong_tuan"), description="Sửa các ngày uống")
    reminder_enabled: Optional[bool] = Field(None, validation_alias=AliasChoices("reminder_enabled", "bat_tat_nhac"), description="Bật/tắt nhắc nhở")

class ScheduleResponse(BaseModel):
    id: int = Field(..., description="ID lịch uống")
    user_medication_id: int = Field(..., description="ID thuốc người dùng")
    medication_name: Optional[str] = Field(None, description="Tên thuốc để hiển thị trên UI")
    schedule_type: ScheduleType = Field(default="co_dinh", description="Loại lịch uống: co_dinh hoặc khi_can")
    intake_time: Optional[str] = None
    days_of_week: Optional[str] = None
    reminder_enabled: bool = True
    effective_from: str = Field(..., description="Thời điểm lịch có hiệu lực [MỚI in v9]")
    status: RecordStatus = Field(default="active", description="active hoặc archived")

class DoseLogItem(BaseModel):
    client_uuid: Optional[str] = Field(None, description="UUID sinh tại mobile để chống ghi trùng khi sync offline (nullable theo v9)")
    medication_schedule_id: int = Field(..., description="ID lịch uống tương ứng")
    scheduled_at: str = Field(..., validation_alias=AliasChoices("scheduled_at", "thoi_gian_du_kien"), description="Thời gian dự kiến uống ISO 8601")
    taken_at: Optional[str] = Field(None, validation_alias=AliasChoices("taken_at", "thoi_gian_thuc_uong"), description="Thời gian thực tế bấm uống (nullable, NULL với Bỏ lỡ)")
    status: DoseStatus = Field(..., validation_alias=AliasChoices("status", "trang_thai"), description="'Đã uống', 'Bỏ lỡ', hoặc 'Uống trễ'")

class DoseSyncResultItem(BaseModel):
    client_uuid: Optional[str] = None
    status: Literal["synced", "duplicate", "error"] = Field(..., description="Trạng thái từng item")
    error_code: Optional[str] = Field(None, description="Mã lỗi nếu thất bại (SCHEDULE_NOT_FOUND, INVALID_STATUS,...)")
    message: Optional[str] = Field(None, description="Mô tả lỗi chi tiết")

class BatchDoseLogSyncSummary(BaseModel):
    synced: int = Field(default=0, description="Số bản ghi ghi nhận mới thành công")
    duplicate: int = Field(default=0, description="Số bản ghi bị trùng client_uuid bỏ qua an toàn")
    error: int = Field(default=0, description="Số bản ghi lỗi cần client xử lý lại")

class BatchDoseLogSyncRequest(BaseModel):
    logs: List[DoseLogItem] = Field(..., min_length=1, description="Danh sách các liều thuốc cần đồng bộ")

class BatchDoseLogSyncResponse(BaseModel):
    summary: BatchDoseLogSyncSummary
    results: List[DoseSyncResultItem]

class DoseLogResponse(BaseModel):
    id: int
    medication_schedule_id: int
    medication_name: Optional[str] = None
    scheduled_at: str
    taken_at: Optional[str] = None
    status: DoseStatus
    client_uuid: Optional[str] = None
    synced_at: Optional[str] = None

class AdherenceSummaryResponse(BaseModel):
    patient_id: str
    period: Literal["7d", "30d"]
    adherence_rate: float = Field(..., description="Tỷ lệ tuân thủ tính theo % (0.0 đến 100.0)")
    taken_on_time: int = Field(..., description="Số liều uống đúng giờ")
    taken_late: int = Field(..., description="Số liều uống trễ")
    missed: int = Field(..., description="Số liều bỏ lỡ")
    total_scheduled: int = Field(..., description="Tổng số liều dự kiến trong kỳ")
