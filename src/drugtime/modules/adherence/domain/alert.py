from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Alert:
    """Push chỉ mang nội dung tối thiểu; nội dung chi tiết đọc qua API (CD6)."""

    notification_id: UUID
    recipient_id: UUID
    device_token: str
    title: str = "DrugTime"
    body: str = "Bạn có cảnh báo mới về người thân"


def dedupe_key(dose_log_id: UUID, recipient_id: UUID) -> str:
    return f"bo_lo:{dose_log_id}:{recipient_id}"
