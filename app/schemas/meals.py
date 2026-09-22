"""AI Meal Suggestion Schemas (Asynchronous & DPIA bounded)."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

JobStatus = Literal["queued", "processing", "completed", "failed"]

class MealSuggestionGenerateRequest(BaseModel):
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] = Field(default="lunch", description="Bữa ăn cần gợi ý")
    ghi_chu_them: Optional[str] = Field(None, description="Ghi chú thêm về khẩu vị hoặc dị ứng")

class MealSuggestionResponse(BaseModel):
    id: int
    user_id: str
    bua_an: str = Field(..., description="Bữa sáng / trưa / tối")
    noi_dung_goi_y: str = Field(..., description="Nội dung giải thích và phân tích dinh dưỡng")
    dua_tren_dieu_kien: List[str] = Field(default_factory=list, description="Bệnh nền đã xét khi gợi ý (tiểu đường, dạ dày...)")
    mon_an_khuyen_nghi: List[str] = Field(default_factory=list, description="Danh sách món ăn phù hợp")
    thuc_pham_tranh: List[str] = Field(default_factory=list, description="Thực phẩm cần tránh do tương tác thuốc")
    ngay_tao: str

class MealSuggestionJobResponse(BaseModel):
    job_id: str = Field(..., description="UUID định danh tiến trình sinh gợi ý nền")
    status: JobStatus = Field(default="queued", description="Trạng thái hàng đợi")
    estimated_seconds: int = Field(default=3, description="Thời gian ước tính hoàn thành (giây)")
    message: str = Field(default="Yêu cầu đang được xử lý trong nền. Vui lòng kiểm tra lại qua job_id.")

class MealSuggestionJobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    result: Optional[MealSuggestionResponse] = None
    error: Optional[str] = None
