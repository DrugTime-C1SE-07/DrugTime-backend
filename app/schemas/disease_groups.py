"""Disease Groups Schemas (Lookup Table in Schema v9 - QA.10, CD8)."""
from typing import Optional
from pydantic import BaseModel, Field

class DiseaseGroupResponse(BaseModel):
    id: int = Field(..., description="ID nhóm bệnh lookup")
    code: str = Field(..., description="Mã nhóm bệnh ổn định (vd: tang_huyet_ap, tieu_duong)")
    name: str = Field(..., description="Tên nhóm bệnh hiển thị")
    is_active: bool = Field(default=True, description="Trạng thái kích hoạt")

class DiseaseGroupCreate(BaseModel):
    code: str = Field(..., description="Mã ổn định duy nhất (vd: tang_huyet_ap, tieu_duong)")
    name: str = Field(..., description="Tên nhóm bệnh hiển thị")
    is_active: bool = Field(default=True, description="Trạng thái kích hoạt")

class DiseaseGroupUpdate(BaseModel):
    code: Optional[str] = Field(None, description="Mã nhóm bệnh")
    name: Optional[str] = Field(None, description="Tên hiển thị")
    is_active: Optional[bool] = Field(None, description="Bật/tắt trạng thái")
