"""AI Meal Suggestion Schemas (Schema v9: English naming, DPIA bounded)."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, AliasChoices

JobStatus = Literal["queued", "processing", "completed", "failed"]

class MealSuggestionGenerateRequest(BaseModel):
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] = Field(default="lunch", description="Bữa ăn cần gợi ý")
    notes: Optional[str] = Field(None, validation_alias=AliasChoices("notes", "ghi_chu_them"), description="Ghi chú thêm về khẩu vị hoặc dị ứng")

class MealSuggestionResponse(BaseModel):
    id: int
    user_id: str
    meal_type: str = Field(..., description="Bữa ăn: Breakfast / Lunch / Dinner")
    suggestion_content: str = Field(..., description="Nội dung giải thích và phân tích dinh dưỡng")
    based_on_conditions: List[str] = Field(default_factory=list, description="Bệnh nền đã xét khi gợi ý")
    recommended_dishes: List[str] = Field(default_factory=list, description="Danh sách món ăn phù hợp")
    foods_to_avoid: List[str] = Field(default_factory=list, description="Thực phẩm cần tránh do tương tác thuốc")
    created_at: str

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
