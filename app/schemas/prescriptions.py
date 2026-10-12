"""Prescriptions & Medications Schemas (Schema v9: English naming, no free text, no unmatched_scans)."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, AliasChoices

InputSource = Literal["ocr_scan", "thu_cong", "mac_dinh"]
PrescriptionStatus = Literal["dang_dung", "da_ket_thuc", "archived"]
RecordStatus = Literal["active", "archived"]

class ActiveIngredientItem(BaseModel):
    id: int = Field(..., description="ID hoạt chất Bảng A")
    standard_name: str = Field(..., description="Tên hoạt chất chuẩn hóa quốc tế")
    strength_value: float = Field(..., description="Giá trị hàm lượng cấu trúc (vd: 500)")
    strength_unit: str = Field(..., description="Đơn vị hàm lượng (vd: mg, mcg)")
    dosing_unit: str = Field(..., description="Đơn vị định lượng (viên, gói, ml)")

class MedicationCatalogResponse(BaseModel):
    id: int = Field(..., description="ID thuốc trong catalog")
    name: str = Field(..., description="Tên thương mại của thuốc")
    raw_active_ingredient: Optional[str] = Field(None, description="Chuỗi hoạt chất thô")
    strength_text: Optional[str] = Field(None, description="Hàm lượng hiển thị")
    dosage_form: Optional[str] = Field(None, description="Dạng bào chế (viên nén, siro,...)")
    manufacturer_name: Optional[str] = None
    manufacturer_country: Optional[str] = None
    packaging_spec: Optional[str] = None
    deleted_at: Optional[str] = Field(None, description="Thời điểm xóa mềm (NULL = đang lưu hành)")

class MedicationDetailResponse(MedicationCatalogResponse):
    active_ingredients: List[ActiveIngredientItem] = Field(default_factory=list, description="Danh sách hoạt chất cấu trúc")

class OcrUploadResponse(BaseModel):
    scanned_text: str = Field(..., description="Văn bản nhận diện thô từ hình ảnh")
    matched_medications: List[MedicationCatalogResponse] = Field(default_factory=list, description="Các loại thuốc khớp trong catalog")
    unmatched_lines: List[str] = Field(default_factory=list, description="Các dòng không khớp cần người dùng kiểm tra")

class UserMedicationCreate(BaseModel):
    medication_id: int = Field(..., description="ID thuốc trong catalog (bắt buộc, không nhập tự do theo Schema v9)")
    entry_method: InputSource = Field(default="thu_cong", validation_alias=AliasChoices("entry_method", "cach_nhap"), description="ocr_scan hoặc thu_cong")
    quantity_per_dose: float = Field(..., gt=0, validation_alias=AliasChoices("quantity_per_dose", "so_luong_moi_lan"), description="Số lượng mỗi lần uống (viên/ml)")
    doses_per_day: int = Field(..., gt=0, le=24, validation_alias=AliasChoices("doses_per_day", "so_lan_moi_ngay"), description="Tần suất số lần uống mỗi ngày")
    dosing_unit: Optional[str] = Field("viên", validation_alias=AliasChoices("dosing_unit", "don_vi_uong"), description="Đơn vị dùng: viên, gói, ml")

class UserMedicationUpdate(BaseModel):
    quantity_per_dose: Optional[float] = Field(None, gt=0, validation_alias=AliasChoices("quantity_per_dose", "so_luong_moi_lan"))
    doses_per_day: Optional[int] = Field(None, gt=0, le=24, validation_alias=AliasChoices("doses_per_day", "so_lan_moi_ngay"))
    confirmation_status: Optional[str] = Field(None, validation_alias=AliasChoices("confirmation_status", "trang_thai_xac_nhan"))

class UserMedicationResponse(BaseModel):
    id: int = Field(..., description="ID thuốc trong đơn của người dùng")
    user_id: str
    prescription_id: int
    medication_id: int
    name: str = Field(..., description="Tên thuốc")
    entry_method: InputSource
    confirmation_status: Optional[str] = None
    quantity_per_dose: float
    doses_per_day: int
    dosing_unit: str = "viên"
    has_interaction_data: bool = True
    status: RecordStatus = Field(default="active", description="active hoặc archived")

class PrescriptionCreate(BaseModel):
    entry_source: InputSource = Field(default="thu_cong", validation_alias=AliasChoices("entry_source", "nguon_nhap"), description="ocr_scan hoặc thu_cong")
    prescribed_date: Optional[str] = Field(None, validation_alias=AliasChoices("prescribed_date", "ngay_ke_don"), description="Ngày kê đơn YYYY-MM-DD")
    prescribing_facility: Optional[str] = Field(None, validation_alias=AliasChoices("prescribing_facility", "noi_ke_don"), description="Nơi kê đơn (Bệnh viện, phòng khám)")
    medications: List[UserMedicationCreate] = Field(default_factory=list, description="Danh sách thuốc trong đơn")

class PrescriptionUpdateMetadata(BaseModel):
    prescribed_date: Optional[str] = Field(None, validation_alias=AliasChoices("prescribed_date", "ngay_ke_don"))
    prescribing_facility: Optional[str] = Field(None, validation_alias=AliasChoices("prescribing_facility", "noi_ke_don"))

class PrescriptionUpdateStatus(BaseModel):
    status: PrescriptionStatus = Field(..., validation_alias=AliasChoices("status", "trang_thai"), description="dang_dung, da_ket_thuc, hoặc archived")

class PrescriptionResponse(BaseModel):
    id: int = Field(..., description="ID đơn thuốc")
    user_id: str
    entry_source: InputSource
    prescribed_date: Optional[str] = None
    prescribing_facility: Optional[str] = None
    status: PrescriptionStatus
    medications: List[UserMedicationResponse] = Field(default_factory=list)
