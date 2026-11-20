"""Chi tiết một thuốc trong danh mục (GET /catalog/medications/{id}, adhoc-20261120).

Danh mục không phải dữ liệu sức khỏe: không kiểm consent, không ghi nhật ký truy cập. Trả cả
thuốc đã xóa mềm vì người bệnh có thể đang dùng (QD-36); tìm kiếm vẫn bỏ qua các thuốc này."""

from typing import Protocol

from drugtime.modules.catalog.domain.medication import CatalogMedicationDetail
from drugtime.shared.errors import NotFound
from drugtime.shared.uow import UnitOfWork

CATALOG_NOT_FOUND = "catalog_medication_not_found"


class CatalogDetailSource(Protocol):
    def get_detail(self, uow: UnitOfWork, medication_id: int) -> CatalogMedicationDetail | None: ...


def get_medication_detail(
    uow: UnitOfWork, medication_id: int, source: CatalogDetailSource
) -> CatalogMedicationDetail:
    found = source.get_detail(uow, medication_id)
    if found is None:
        raise NotFound(CATALOG_NOT_FOUND)
    return found
