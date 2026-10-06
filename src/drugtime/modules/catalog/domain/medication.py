from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogMedication:
    """Thông tin hiển thị của một thuốc trong danh mục."""

    id: int
    name: str
    strength_text: str | None
    dosage_form: str | None
    has_active_ingredients: bool  # False = chưa đủ dữ liệu để kiểm tương tác
    active_ingredient: str | None = None  # medications.raw_active_ingredient, chỉ để hiển thị
