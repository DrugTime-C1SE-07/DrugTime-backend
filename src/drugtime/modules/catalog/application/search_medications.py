"""Tìm thuốc trong danh mục (GET /catalog/medications). Danh mục không phải dữ liệu sức khỏe:
không kiểm consent, không ghi nhật ký truy cập."""

from typing import Protocol

from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.shared.uow import UnitOfWork


class CatalogSearch(Protocol):
    def search(self, uow: UnitOfWork, escaped: str, limit: int) -> list[CatalogMedication]: ...


def escape_like(value: str) -> str:
    """Escape ký tự đặc biệt của LIKE (ESCAPE '\\') để người dùng không gõ được wildcard."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_medications(
    uow: UnitOfWork, query: str, limit: int, catalog: CatalogSearch
) -> list[CatalogMedication]:
    q = query.strip()
    if not q:
        return []  # route đã chặn bằng pattern; giữ để hàm an toàn khi gọi trực tiếp
    return catalog.search(uow, escape_like(q), limit)
