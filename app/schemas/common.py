"""Common response envelopes, pagination, and error structures."""
from typing import Generic, TypeVar, Optional, List, Any, Dict
from pydantic import BaseModel, Field

T = TypeVar("T")

class ErrorDetail(BaseModel):
    code: str = Field(..., description="Mã lỗi hệ thống định danh duy nhất (VD: NOT_FOUND, CONSENT_REQUIRED)")
    message: str = Field(..., description="Thông điệp lỗi chi tiết cho người dùng")
    details: Optional[List[Dict[str, Any]]] = Field(default=None, description="Chi tiết lỗi theo từng trường dữ liệu")

class ResponseEnvelope(BaseModel, Generic[T]):
    success: bool = Field(default=True, description="Trạng thái thực thi của request")
    data: Optional[T] = Field(default=None, description="Dữ liệu phản hồi")
    message: Optional[str] = Field(default=None, description="Thông điệp thành công (nếu có)")

class ErrorEnvelope(BaseModel):
    success: bool = Field(default=False, description="Luôn là False khi có lỗi")
    data: Optional[Any] = Field(default=None, description="Luôn là None khi lỗi")
    error: ErrorDetail = Field(..., description="Thông tin lỗi")

class PaginationMeta(BaseModel):
    page: int = Field(default=1, ge=1, description="Trang hiện tại")
    page_size: int = Field(default=20, ge=1, le=100, description="Số phần tử mỗi trang")
    total_items: int = Field(..., description="Tổng số phần tử")
    total_pages: int = Field(..., description="Tổng số trang")

class PaginatedData(BaseModel, Generic[T]):
    items: List[T] = Field(default_factory=list, description="Danh sách các phần tử của trang hiện tại")
    pagination: PaginationMeta = Field(..., description="Thông tin phân trang")

class MessageResponse(BaseModel):
    message: str = Field(..., description="Thông báo trạng thái thực thi")
