"""Tìm thuốc trong danh mục (GET /catalog/medications). Danh mục không phải dữ liệu sức khỏe:
không kiểm consent, không ghi nhật ký truy cập.

So khớp theo **từ** (contract, adhoc-20261116 B8): mỗi từ của câu tìm phải nằm trong tên, hoạt
chất hoặc hàm lượng; số đứng trước đơn vị được ghép thành một từ ("500 mg" = "500mg")."""

import re
from typing import Protocol

from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.shared.uow import UnitOfWork

# Chặn chi phí truy vấn: mỗi từ là một điều kiện. `q` tối đa 100 ký tự nên 8 là đủ cho tên
# thuốc + hàm lượng.
MAX_SEARCH_TERMS = 8

_UNITS = frozenset({"mg", "mcg", "g", "ml", "iu", "ui", "%"})
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class CatalogSearch(Protocol):
    def search(
        self, uow: UnitOfWork, terms: list[str], query: str, limit: int
    ) -> list[CatalogMedication]: ...


def escape_like(value: str) -> str:
    """Escape ký tự đặc biệt của LIKE (ESCAPE '\\') để người dùng không gõ được wildcard."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_terms(query: str) -> list[str]:
    """Các từ để so khớp, chữ thường, chưa escape. Dấu tiếng Việt để DB bỏ (catalog_search_key)."""
    words = query.lower().split()
    terms: list[str] = []
    i = 0
    while i < len(words):
        word = words[i]
        if _NUMBER.fullmatch(word) and i + 1 < len(words) and words[i + 1] in _UNITS:
            word += words[i + 1]
            i += 1
        if word not in terms:
            terms.append(word)
        i += 1
    return terms[:MAX_SEARCH_TERMS]


def search_medications(
    uow: UnitOfWork, query: str, limit: int, catalog: CatalogSearch
) -> list[CatalogMedication]:
    terms = search_terms(query)
    if not terms:
        return []  # route đã chặn bằng pattern; giữ để hàm an toàn khi gọi trực tiếp
    return catalog.search(
        uow, [escape_like(t) for t in terms], escape_like(" ".join(query.split())), limit
    )
