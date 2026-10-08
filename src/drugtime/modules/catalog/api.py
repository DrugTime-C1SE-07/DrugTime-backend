"""Public facade of the catalog module."""

from collections.abc import Callable
from datetime import datetime

from drugtime.modules.catalog.adapters.inbound.http import router
from drugtime.modules.catalog.adapters.outbound.job_queue import enqueue_sync
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.application.scheduling import is_sync_due
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.catalog.repository import CatalogSyncRepository
from drugtime.shared.clock import now
from drugtime.shared.uow import UnitOfWork

__all__ = ["CatalogMedication", "get_medication", "router", "sync_if_due"]


def get_medication(
    uow: UnitOfWork, medication_id: int, *, include_deleted: bool = False
) -> CatalogMedication | None:
    return SqlCatalog().get_medication(uow, medication_id, include_deleted=include_deleted)


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
