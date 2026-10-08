from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogMedication:
    """Thông tin hiển thị của một thuốc trong danh mục (phục vụ tìm kiếm K04, Mobile)."""

    id: int
    name: str
    strength_text: str | None
    dosage_form: str | None
    has_active_ingredients: bool  # False = chưa đủ dữ liệu để kiểm tương tác
    active_ingredient: str | None = None  # medications.raw_active_ingredient, chỉ để hiển thị


@dataclass(frozen=True, slots=True)
class Medication:
    """Chi tiết đầy đủ của một bản ghi thuốc (Admin CRUD PB04)."""

    id: int
    name: str
    raw_active_ingredient: str | None = None
    strength_text: str | None = None
    dosage_form: str | None = None
    manufacturer_name: str | None = None
    manufacturer_country: str | None = None
    packaging_spec: str | None = None
    source: str | None = None
    source_ref: str | None = None
    deleted_at: str | None = None
