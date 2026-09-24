"""Prescriptions & Medications Schemas."""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

InputSource = Literal["ocr_scan", "thu_cong", "mac_dinh"]
PrescriptionStatus = Literal["dang_dung", "da_ket_thuc", "archived"]
RecordStatus = Literal["active", "archived"]

class ActiveIngredientItem(BaseModel):
    id: int = Field(..., description="ID hoạt chất Bảng A")
    ten_hoat_chat_chuan: str = Field(..., description="Tên hoạt chất chuẩn hóa quốc tế")
    ham_luong_value: float = Field(..., description="Giá trị hàm lượng cấu trúc (vd: 500)")
    ham_luong_unit: str = Field(..., description="Đơn vị hàm lượng (vd: mg, mcg)")
    don_vi_dinh_luong: str = Field(..., description="Đơn vị định lượng (viên, gói, ml)")

class MedicationCatalogResponse(BaseModel):
    id: int = Field(..., description="ID thuốc trong catalog")
    ten_thuoc: str = Field(..., description="Tên thương mại của thuốc")
    hoat_chat_raw: Optional[str] = Field(None, description="Chuỗi hoạt chất thô")
    ham_luong: Optional[str] = Field(None, description="Hàm lượng hiển thị")
    dang_bao_che: Optional[str] = Field(None, description="Dạng bào chế (viên nén, siro,...)")
    cty_san_xuat_ten: Optional[str] = None
    cty_san_xuat_nuoc: Optional[str] = None
    quy_cach_dong_goi: Optional[str] = None

class MedicationDetailResponse(MedicationCatalogResponse):
    active_ingredients: List[ActiveIngredientItem] = Field(default_factory=list, description="Danh sách hoạt chất cấu trúc")

class UnmatchedScanCreate(BaseModel):
    chuoi_nhan_dien: str = Field(..., description="Chuỗi OCR blister không khớp catalog")

class UnmatchedScanResponse(BaseModel):
    id: int = Field(...)
    user_id: str = Field(...)
    chuoi_nhan_dien: str = Field(...)
    thoi_gian: str = Field(...)
    admin_da_xem_xet: bool = Field(default=False)

class OcrUploadResponse(BaseModel):
    scanned_text: str = Field(..., description="Văn bản nhận diện thô từ hình ảnh")
    matched_medications: List[MedicationCatalogResponse] = Field(default_factory=list, description="Các loại thuốc khớp trong catalog")
    unmatched_lines: List[str] = Field(default_factory=list, description="Các dòng không khớp cần người dùng kiểm tra")

class UserMedicationCreate(BaseModel):
    medication_id: Optional[int] = Field(None, description="ID thuốc trong catalog (nếu khớp)")
    ten_thuoc_tu_nhap: Optional[str] = Field(None, description="Tên tự nhập nếu không có trong catalog")
    cach_nhap: InputSource = Field(default="thu_cong", description="ocr_scan hoặc thu_cong")
    so_luong_moi_lan: float = Field(..., gt=0, description="Số lượng mỗi lần uống (viên/ml)")
    so_lan_moi_ngay: int = Field(..., gt=0, le=24, description="Tần suất số lần uống mỗi ngày")
    don_vi_uong: Optional[str] = Field("viên", description="Đơn vị dùng: viên, gói, ml")

class UserMedicationUpdate(BaseModel):
    so_luong_moi_lan: Optional[float] = Field(None, gt=0)
    so_lan_moi_ngay: Optional[int] = Field(None, gt=0, le=24)
    trang_thai_xac_nhan: Optional[str] = Field(None, description="Trạng thái xác nhận sau OCR scan")

class UserMedicationResponse(BaseModel):
    id: int = Field(..., description="ID thuốc trong đơn của người dùng")
    user_id: str = Field(...)
    don_thuoc_id: int = Field(...)
    medication_id: Optional[int] = None
    ten_thuoc: str = Field(..., description="Tên hiển thị của thuốc")
    cach_nhap: InputSource
    trang_thai_xac_nhan: Optional[str] = None
    so_luong_moi_lan: float
    so_lan_moi_ngay: int
    don_vi_uong: str = "viên"
    co_du_lieu_tuong_tac: bool = True
    trang_thai: RecordStatus = Field(default="active", description="active hoặc archived (soft-delete)")

class PrescriptionCreate(BaseModel):
    nguon_nhap: InputSource = Field(default="thu_cong", description="ocr_scan hoặc thu_cong")
    ngay_ke_don: Optional[str] = Field(None, description="Ngày kê đơn YYYY-MM-DD")
    noi_ke_don: Optional[str] = Field(None, description="Nơi kê đơn (Bệnh viện, phòng khám)")
    medications: List[UserMedicationCreate] = Field(default_factory=list, description="Danh sách thuốc trong đơn")

class PrescriptionUpdateMetadata(BaseModel):
    ngay_ke_don: Optional[str] = Field(None, description="Cập nhật ngày kê đơn")
    noi_ke_don: Optional[str] = Field(None, description="Cập nhật nơi kê đơn")

class PrescriptionUpdateStatus(BaseModel):
    trang_thai: PrescriptionStatus = Field(..., description="dang_dung, da_ket_thuc, hoặc archived")

class PrescriptionResponse(BaseModel):
    id: int = Field(..., description="ID đơn thuốc")
    user_id: str = Field(...)
    nguon_nhap: InputSource
    ngay_ke_don: Optional[str] = None
    noi_ke_don: Optional[str] = None
    trang_thai: PrescriptionStatus
    medications: List[UserMedicationResponse] = Field(default_factory=list)
