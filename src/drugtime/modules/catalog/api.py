"""Public facade of the catalog module."""

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter

from drugtime.modules.catalog.adapters.inbound.conditions_http import router as _conditions_router
from drugtime.modules.catalog.adapters.inbound.http import router as _catalog_router
from drugtime.modules.catalog.adapters.outbound.job_queue import enqueue_sync
from drugtime.modules.catalog.adapters.outbound.sql_active_ingredients import SqlActiveIngredients
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.adapters.outbound.sql_conditions import SqlConditions
from drugtime.modules.catalog.application.list_active_ingredients import normalize_query
from drugtime.modules.catalog.application.scheduling import is_sync_due
from drugtime.modules.catalog.domain.condition import Condition
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.catalog.repository import CatalogSyncRepository
from drugtime.shared.clock import now
from drugtime.shared.uow import UnitOfWork

__all__ = [
    "Condition",
    "get_condition",
    "condition_names",
    "CatalogMedication",
    "existing_ingredient_ids",
    "get_medication",
    "ingredient_ids_matching",
    "ingredient_ids_of_medication",
    "ingredient_names",
    "router",
    "sync_if_due",
]

router = APIRouter()
router.include_router(_catalog_router)
router.include_router(_conditions_router)


def get_condition(uow: UnitOfWork, condition_id: int) -> Condition | None:
    return SqlConditions().get(uow, condition_id)


def condition_names(uow: UnitOfWork, ids: list[int]) -> dict[int, str]:
    return SqlConditions().names(uow, ids)


def get_medication(
    uow: UnitOfWork, medication_id: int, *, include_deleted: bool = False
) -> CatalogMedication | None:
    return SqlCatalog().get_medication(uow, medication_id, include_deleted=include_deleted)


def existing_ingredient_ids(uow: UnitOfWork, ids: list[int]) -> set[int]:
    """Các id trong `ids` có trong bảng hoạt chất."""
    return SqlActiveIngredients().existing_ids(uow, ids)


def ingredient_names(uow: UnitOfWork, ids: list[int]) -> dict[int, str]:
    """Tên chuẩn theo id hoạt chất; id không tồn tại bị bỏ qua."""
    return SqlActiveIngredients().names(uow, ids)


def ingredient_ids_matching(uow: UnitOfWork, q: str) -> list[int]:
    """Id hoạt chất có tên chuẩn hoặc alias chứa `q` (không phân biệt hoa thường)."""
    escaped = normalize_query(q)
    return [] if escaped is None else SqlActiveIngredients().ids_matching(uow, escaped)


def ingredient_ids_of_medication(uow: UnitOfWork, medication_id: int) -> list[int]:
    """Id các hoạt chất của một thuốc trong danh mục; rỗng nếu thuốc không có hoặc chưa ánh xạ."""
    return SqlActiveIngredients().ids_of_medication(uow, medication_id)


def sync_if_due(
    uow_factory,
    *,
    repository: CatalogSyncRepository | None = None,
    enqueue: Callable[..., str] = enqueue_sync,
    now_fn: Callable[[], datetime] = now,
) -> str | None:
    """Enqueue the DAV synchronization task when its seven-day interval is due."""
    source = "dav_drugbank"
    repository = repository or CatalogSyncRepository()
    with uow_factory() as uow:
        if repository.is_running(uow, source):
            return None
        last_success_at = repository.latest_success_at(uow, source)

    if not is_sync_due(last_success_at, now_fn()):
        return None
    return enqueue(source, triggered_by="scheduler")
