"""Giao diện công khai của catalog."""

from drugtime.modules.catalog.adapters.inbound.http import router
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.shared.uow import UnitOfWork

__all__ = ["CatalogMedication", "get_medication", "router", "run_sync", "sync_if_due"]


def get_medication(
    uow: UnitOfWork, medication_id: int, *, include_deleted: bool = False
) -> CatalogMedication | None:
    """Thuốc trong danh mục; None nếu không có hoặc đã xóa mềm (trừ khi include_deleted)."""
    return SqlCatalog().get_medication(uow, medication_id, include_deleted=include_deleted)


def sync_if_due(uow_factory) -> None:
    """Tick: chạy đồng bộ nếu lượt thanh_cong gần nhất của từng source đã quá hạn
    (tính theo Asia/Ho_Chi_Minh, đọc catalog_sync_runs). CD10."""
    # TODO: task catalog sync (Sprint 4)


def run_sync(uow_factory, source: str | None = None) -> None:
    """DW2: tạo dòng catalog_sync_runs 'dang_chay', gọi nguồn, upsert (xóa mềm), cập nhật dòng."""
    raise NotImplementedError  # TODO: task catalog sync (Sprint 4)
