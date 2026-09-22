"""Schedules & Dose Logs Schemas."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

LoaiLich = Literal["co_dinh", "khi_can"]
DoseStatus = Literal["Đã uống", "Bỏ lỡ", "Uống trễ"]
RecordStatus = Literal["active", "archived"]

class ScheduleCreate(BaseModel):
    loai_lich: LoaiLich = Field(default="co_dinh", description="co_dinh (giờ cố định) hoặc khi_can (PRN - khi cần)")
    gio_uong: Optional[str] = Field("08:00", description="Giờ uống định dạng HH:MM (bắt buộc khi co_dinh)")
    ngay_trong_tuan: Optional[str] = Field("2,3,4,5,6,7,CN", description="Danh sách các thứ trong tuần")
    bat_tat_nhac: bool = Field(default=True, description="Bật hoặc tắt nhắc nhở cho khung giờ này")

class ScheduleUpdate(BaseModel):
    gio_uong: Optional[str] = Field(None, description="Sửa giờ uống HH:MM")
    ngay_trong_tuan: Optional[str] = Field(None, description="Sửa các ngày uống")
    bat_tat_nhac: Optional[bool] = Field(None, description="Bật/tắt nhắc nhở")

class ScheduleResponse(BaseModel):
    id: int = Field(..., description="ID lịch uống")
    user_medication_id: int = Field(..., description="ID thuốc người dùng")
    ten_thuoc: Optional[str] = Field(None, description="Tên thuốc để hiển thị trên UI")
    loai_lich: LoaiLich = Field(default="co_dinh", description="Loại lịch uống: co_dinh hoặc khi_can")
    gio_uong: Optional[str] = None
    ngay_trong_tuan: Optional[str] = None
    bat_tat_nhac: bool = True
    trang_thai: RecordStatus = Field(default="active", description="active hoặc archived")

class DoseLogItem(BaseModel):
    client_uuid: str = Field(..., description="UUID sinh tại mobile để chống ghi trùng khi sync offline")
    medication_schedule_id: int = Field(..., description="ID lịch uống tương ứng")
    thoi_gian_du_kien: str = Field(..., description="Thời gian dự kiến uống ISO 8601")
    thoi_gian_thuc_uong: Optional[str] = Field(None, description="Thời gian thực tế bấm uống ISO 8601")
    trang_thai: DoseStatus = Field(..., description="'Đã uống', 'Bỏ lỡ', hoặc 'Uống trễ'")

class DoseSyncResultItem(BaseModel):
    client_uuid: str = Field(...)
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
    ten_thuoc: Optional[str] = None
    thoi_gian_du_kien: str
    thoi_gian_thuc_uong: Optional[str] = None
    trang_thai: DoseStatus
    client_uuid: str
    dong_bo_luc: Optional[str] = None

class AdherenceSummaryResponse(BaseModel):
    patient_id: str
    period: Literal["7d", "30d"]
    adherence_rate: float = Field(..., description="Tỷ lệ tuân thủ tính theo % (0.0 đến 100.0)")
    taken_on_time: int = Field(..., description="Số liều uống đúng giờ")
    taken_late: int = Field(..., description="Số liều uống trễ")
    missed: int = Field(..., description="Số liều bỏ lỡ")
    total_scheduled: int = Field(..., description="Tổng số liều dự kiến trong kỳ")
