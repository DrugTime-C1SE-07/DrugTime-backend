"""List catalog synchronization history for Admin users."""

from typing import Protocol

from drugtime.modules.catalog.domain.sync_run import (
    CatalogSyncRunPage,
    CatalogSyncSource,
    CatalogSyncStatus,
)
from drugtime.shared.uow import UnitOfWork


class SyncRunReader(Protocol):
    def list_runs(
        self,
        uow: UnitOfWork,
        *,
        source: CatalogSyncSource | None,
        status: CatalogSyncStatus | None,
        limit: int,
        offset: int,
    ) -> CatalogSyncRunPage: ...


def list_sync_runs(
    uow: UnitOfWork,
    reader: SyncRunReader,
    *,
    source: CatalogSyncSource | None = None,
    status: CatalogSyncStatus | None = None,
    limit: int = 20,
    offset: int = 0,
) -> CatalogSyncRunPage:
    return reader.list_runs(uow, source=source, status=status, limit=limit, offset=offset)
