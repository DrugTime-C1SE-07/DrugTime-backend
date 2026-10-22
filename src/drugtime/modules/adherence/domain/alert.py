from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Alert:
    """Push chỉ mang nội dung tối thiểu; nội dung chi tiết đọc qua API (CD6)."""

    notification_id: int
    recipient_id: UUID
    device_token: str
    title: str = "DrugTime"
    body: str = "Bạn có cảnh báo mới về người thân"


@dataclass(frozen=True)
class NotificationRecord:
    id: int
    user_id: UUID
    about_patient_user_id: UUID | None
    type: str
    content: str
    is_read: bool
    created_at: datetime
    about_patient_name: str | None = None
    # Snapshot lúc tạo sự kiện; null dành cho dữ liệu cũ chưa có snapshot đáng tin cậy.
    medication_name: str | None = None
    scheduled_at: datetime | None = None


# Mỗi liều bỏ lỡ chỉ sinh một notification cho từng người nhận, kể cả khi quét chồng lấn.
def dedupe_key(dose_log_id: int, recipient_id: UUID) -> str:
    return f"bo_lo:{dose_log_id}:{recipient_id}"
