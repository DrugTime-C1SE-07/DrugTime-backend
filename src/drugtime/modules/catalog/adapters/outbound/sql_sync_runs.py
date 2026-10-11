"""SQL reader for catalog synchronization history."""

from sqlalchemy import text

from drugtime.modules.catalog.domain.sync_run import (
    CatalogSyncRun,
    CatalogSyncRunPage,
    CatalogSyncSource,
    CatalogSyncStatus,
    CatalogSyncTrigger,
    sanitize_error_details,
)
from drugtime.shared.uow import UnitOfWork


class SqlSyncRuns:
    def list_runs(
        self,
        uow: UnitOfWork,
        *,
        source: CatalogSyncSource | None,
        status: CatalogSyncStatus | None,
        limit: int,
        offset: int,
    ) -> CatalogSyncRunPage:
        params = {
            "source": None if source is None else source.value,
            "status": None if status is None else status.value,
            "limit": limit,
            "offset": offset,
        }
        rows = uow.connection.execute(
            text(
                "SELECT id, source::text AS source, started_at, finished_at, "
                "status::text AS status, records_inserted, records_updated, records_failed, "
                "error_details, triggered_by::text AS triggered_by, count(*) OVER() AS total "
                "FROM catalog_sync_runs "
                "WHERE (CAST(:source AS catalog_source) IS NULL "
                "OR source=CAST(:source AS catalog_source)) "
                "AND (CAST(:status AS sync_status) IS NULL "
                "OR status=CAST(:status AS sync_status)) "
                "ORDER BY started_at DESC, id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
        if rows:
            total = int(rows[0].total)
        else:
            total = int(
                uow.connection.execute(
                    text(
                        "SELECT count(*) FROM catalog_sync_runs "
                        "WHERE (CAST(:source AS catalog_source) IS NULL "
                        "OR source=CAST(:source AS catalog_source)) "
                        "AND (CAST(:status AS sync_status) IS NULL "
                        "OR status=CAST(:status AS sync_status))"
                    ),
                    params,
                ).scalar_one()
            )
        items = [
            CatalogSyncRun(
                id=int(row.id),
                source=CatalogSyncSource(row.source),
                started_at=row.started_at,
                finished_at=row.finished_at,
                status=CatalogSyncStatus(row.status),
                records_inserted=row.records_inserted,
                records_updated=row.records_updated,
                records_failed=row.records_failed,
                error_details=sanitize_error_details(row.error_details),
                triggered_by=CatalogSyncTrigger(row.triggered_by),
            )
            for row in rows
        ]
        return CatalogSyncRunPage(items=items, total=total, limit=limit, offset=offset)
