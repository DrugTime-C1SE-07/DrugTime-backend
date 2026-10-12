"""Medical Conditions & Health Profile Schemas (Schema v9: English naming, stage)."""
from typing import Optional, Literal
from pydantic import BaseModel, Field, AliasChoices

MedicalNature = Literal["benh_ly", "sinh_ly_binh_thuong"]
DataRole = Literal["sinh_hoat_chat_dieu_tri", "dieu_chinh_thuoc_khac"]
RecordStatus = Literal["active", "archived"]

class ConditionCatalogResponse(BaseModel):
    id: int = Field(..., description="ID điều kiện y khoa chuẩn hóa (Bảng B)")
    name: str = Field(..., description="Tên bệnh lý hoặc điều kiện sinh lý")
    medical_nature: MedicalNature = Field(..., description="benh_ly hoặc sinh_ly_binh_thuong")
    data_role: DataRole = Field(..., description="sinh_hoat_chat_dieu_tri hoặc dieu_chinh_thuoc_khac")
    icd10_code: Optional[str] = Field(None, description="Mã ICD-10 chuẩn quốc tế")

class UserConditionCreate(BaseModel):
    condition_id: int = Field(..., description="ID điều kiện y khoa từ catalog")
    subtype: Optional[str] = Field(None, description="Phân type (chỉ áp dụng cho Tiểu đường, ví dụ: Type 1, Type 2)")
    stage: Optional[str] = Field(None, validation_alias=AliasChoices("stage", "phan_do"), description="Phân độ (chỉ áp dụng cho Suy thận mạn, ví dụ: Giai đoạn 3a)")

class UserConditionResponse(BaseModel):
    id: int = Field(..., description="ID bản ghi bệnh nền của người dùng")
    user_id: str = Field(..., description="ID bệnh nhân")
    condition_id: int = Field(..., description="ID điều kiện catalog")
    name: str = Field(..., description="Tên bệnh nền")
    subtype: Optional[str] = None
    stage: Optional[str] = None
    status: RecordStatus = Field(default="active", description="active hoặc archived")
