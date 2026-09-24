"""Drug Safety & Interaction Warning Schemas."""
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

FindingSource = Literal["interactions", "drug_food", "precautions", "drug_classes"]
HandlingType = Literal["tranh_phoi_hop", "can_theo_doi", "cach_gio", "giam_lieu"]

class RegimenFindingResponse(BaseModel):
    id: int = Field(..., description="ID phát hiện tương tác")
    snapshot_id: int = Field(...)
    loai_canh_bao: str = Field(..., description="Tương tác thuốc-thuốc / thuốc-thức ăn / thuốc-bệnh nền")
    nguon_bang: FindingSource = Field(..., description="Bảng dữ liệu nguồn (interactions, drug_food, precautions)")
    muc_do: int = Field(..., ge=1, le=4, description="Mức độ nghiêm trọng từ 1 (nhẹ) đến 4 (chống chỉ định tuyệt đối)")
    mo_ta: str = Field(..., description="Mô tả cơ chế và biểu hiện lâm sàng")
    loai_xu_ly: HandlingType = Field(..., description="Hướng xử lý: tranh_phoi_hop, can_theo_doi, cach_gio, giam_lieu")
    khoang_cach_gio: Optional[float] = Field(None, description="Khoảng cách tối thiểu giữa 2 lần uống (nếu loai_xu_ly = cach_gio)")
    disclaimer: str = Field(
        default="Cảnh báo này có tính chất tham khảo y khoa, không thay thế cho chỉ định trực tiếp của bác sĩ hoặc dược sĩ chuyên môn.",
        description="Miễn trừ trách nhiệm y khoa bắt buộc (QA.04)"
    )
    related_medication_ids: List[int] = Field(default_factory=list, description="Danh sách các user_medication_id liên quan")

class RegimenSnapshotResponse(BaseModel):
    id: int = Field(..., description="ID phiên phân tích an toàn")
    user_id: str = Field(...)
    thoi_gian_phan_tich: str
    finding_count: int = Field(..., description="Số lượng cảnh báo phát hiện")
    highest_severity: int = Field(default=1, description="Mức độ cảnh báo cao nhất (1-4)")

class QuickCheckRequest(BaseModel):
    medication_ids: List[int] = Field(..., min_length=1, description="Danh sách ID thuốc dự kiến kê")
    condition_ids: List[int] = Field(default_factory=list, description="Danh sách ID bệnh nền dự kiến xét")

class QuickCheckWarningItem(BaseModel):
    loai: str
    cap_doi: str
    muc_do: int
    mo_ta: str
    loai_xu_ly: str

class QuickCheckResponse(BaseModel):
    safe: bool = Field(..., description="True nếu không có chống chỉ định mức 3-4")
    highest_severity: int = Field(..., description="Mức độ cao nhất tìm thấy")
    warnings: List[QuickCheckWarningItem] = Field(default_factory=list)

class AcknowledgeRecommendationRequest(BaseModel):
    da_xem: bool = Field(default=True)
    da_xu_ly: bool = Field(default=False)
