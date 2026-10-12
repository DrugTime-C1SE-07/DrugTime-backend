"""Drug Safety & Interaction Warning Schemas (Schema v9: English naming, pure rule-based)."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, AliasChoices

FindingSource = Literal["interactions", "drug_food", "precautions", "drug_classes"]
HandlingType = Literal["tranh_phoi_hop", "can_theo_doi", "cach_gio", "giam_lieu"]

class RegimenFindingResponse(BaseModel):
    id: int = Field(..., description="ID phát hiện tương tác")
    snapshot_id: int = Field(...)
    warning_type: str = Field(..., description="Loại cảnh báo (thuốc-thuốc / thuốc-thức ăn / thuốc-bệnh nền)")
    source_table: FindingSource = Field(..., description="Bảng dữ liệu nguồn (interactions, drug_food, precautions, drug_classes)")
    source_id: Optional[int] = Field(None, description="ID bản ghi trong bảng nguồn")
    severity_level: int = Field(..., ge=1, le=4, description="Mức độ nghiêm trọng từ 1 (nhẹ) đến 4 (chống chỉ định tuyệt đối)")
    description: str = Field(..., description="Mô tả cơ chế và biểu hiện lâm sàng")
    handling_type: HandlingType = Field(..., description="Hướng xử lý: tranh_phoi_hop, can_theo_doi, cach_gio, giam_lieu")
    min_interval_hours: Optional[float] = Field(None, description="Khoảng cách tối thiểu giữa 2 lần uống (nếu handling_type = cach_gio)")
    disclaimer: str = Field(
        default="Cảnh báo này có tính chất tham khảo y khoa, không thay thế cho chỉ định trực tiếp của bác sĩ hoặc dược sĩ chuyên môn.",
        description="Miễn trừ trách nhiệm y khoa bắt buộc (QA.04)"
    )
    related_medication_ids: List[int] = Field(default_factory=list, description="Danh sách các user_medication_id liên quan")
    is_shown_to_user: bool = Field(default=True, description="Cờ hiển thị cho người dùng")

class RegimenSnapshotResponse(BaseModel):
    id: int = Field(..., description="ID phiên phân tích an toàn")
    user_id: str = Field(...)
    analyzed_at: str = Field(..., description="Thời điểm phân tích")
    finding_count: int = Field(..., description="Số lượng cảnh báo phát hiện")
    highest_severity: int = Field(default=1, description="Mức độ cảnh báo cao nhất (1-4)")

class QuickCheckRequest(BaseModel):
    medication_ids: List[int] = Field(..., min_length=1, description="Danh sách ID thuốc dự kiến kê")
    condition_ids: List[int] = Field(default_factory=list, description="Danh sách ID bệnh nền dự kiến xét")

class QuickCheckWarningItem(BaseModel):
    warning_type: str = Field(..., description="Loại cảnh báo")
    pair: str = Field(..., description="Cặp tương tác")
    severity_level: int = Field(..., description="Mức độ nghiêm trọng (1-4)")
    description: str = Field(..., description="Mô tả chi tiết")
    handling_type: str = Field(..., description="Hướng xử lý")

class QuickCheckResponse(BaseModel):
    safe: bool = Field(..., description="True nếu không có chống chỉ định mức 3-4")
    highest_severity: int = Field(..., description="Mức độ cao nhất tìm thấy")
    warnings: List[QuickCheckWarningItem] = Field(default_factory=list)

class AcknowledgeRecommendationRequest(BaseModel):
    is_viewed: bool = Field(default=True, validation_alias=AliasChoices("is_viewed", "da_xem"), description="Đánh dấu đã xem")
    is_handled: bool = Field(default=False, validation_alias=AliasChoices("is_handled", "da_xu_ly"), description="Đánh dấu đã xử lý")
