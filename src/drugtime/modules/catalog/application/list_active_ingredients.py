"""Tra cứu hoạt chất trong danh mục cho admin (GET /admin/active-ingredients, task 2.16).
Danh mục không phải dữ liệu sức khỏe: không kiểm consent, không ghi nhật ký truy cập."""

from dataclasses import dataclass, field
from typing import Protocol

from drugtime.modules.catalog.application.search_medications import escape_like
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class ActiveIngredient:
    id: int
    standard_name: str
    atc_code: str | None
    pharmacological_group: str | None
    aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActiveIngredientPage:
    items: list[ActiveIngredient]
    total: int


class ActiveIngredientReader(Protocol):
    def list(
        self,
        uow: UnitOfWork,
        *,
        escaped: str | None,
        medication_id: int | None,
        skip: int,
        limit: int,
    ) -> ActiveIngredientPage: ...


def normalize_query(q: str | None) -> str | None:
    """Bỏ khoảng trắng hai đầu và escape wildcard; chuỗi rỗng coi như không lọc."""
    if q is None or not q.strip():
        return None
    return escape_like(q.strip())


def list_active_ingredients(
    uow: UnitOfWork,
    reader: ActiveIngredientReader,
    *,
    q: str | None = None,
    medication_id: int | None = None,
    skip: int = 0,
    limit: int = 20,
) -> ActiveIngredientPage:
    return reader.list(
        uow, escaped=normalize_query(q), medication_id=medication_id, skip=skip, limit=limit
    )
