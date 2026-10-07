"""SQL persistence for catalog synchronization."""

from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import text

from drugtime.modules.catalog.normalize import NormalizedMedication
from drugtime.shared.uow import UnitOfWork

_UPSERT = text(
    "INSERT INTO medications "
    "(name, raw_active_ingredient, strength_text, dosage_form, manufacturer_name, "
    "manufacturer_country, packaging_spec, source, source_ref, deleted_at) VALUES "
    "(:name, :raw_active_ingredient, :strength_text, :dosage_form, :manufacturer_name, "
    ":manufacturer_country, :packaging_spec, :source, :source_ref, "
    "CASE WHEN :withdrawn THEN now() ELSE NULL END) "
    "ON CONFLICT (source, source_ref) DO UPDATE SET "
    "name=EXCLUDED.name, raw_active_ingredient=EXCLUDED.raw_active_ingredient, "
    "strength_text=EXCLUDED.strength_text, dosage_form=EXCLUDED.dosage_form, "
    "manufacturer_name=EXCLUDED.manufacturer_name, "
    "manufacturer_country=EXCLUDED.manufacturer_country, "
    "packaging_spec=EXCLUDED.packaging_spec, deleted_at=EXCLUDED.deleted_at"
)


class CatalogSyncRepository:
    def latest_success_at(self, uow: UnitOfWork, source: str) -> datetime | None:
        return uow.connection.execute(
            text(
                "SELECT max(finished_at) FROM catalog_sync_runs "
                "WHERE source=:source AND status='thanh_cong'"
            ),
            {"source": source},
        ).scalar_one()

    def is_running(self, uow: UnitOfWork, source: str) -> bool:
        return bool(
            uow.connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM catalog_sync_runs "
                    "WHERE source=:source AND status='dang_chay')"
                ),
                {"source": source},
            ).scalar_one()
        )

    def start_run(self, uow: UnitOfWork, source: str, triggered_by: str) -> int | None:
        row = uow.connection.execute(
            text(
                "INSERT INTO catalog_sync_runs (source, triggered_by) "
                "VALUES (:source, :triggered_by) "
                "ON CONFLICT DO NOTHING RETURNING id"
            ),
            {"source": source, "triggered_by": triggered_by},
        ).one_or_none()
        return None if row is None else int(row.id)

    def upsert_medications(
        self, uow: UnitOfWork, source: str, medications: Iterable[NormalizedMedication]
    ) -> tuple[int, int]:
        rows = [{**asdict(item), "source": source} for item in medications]
        if not rows:
            return 0, 0

        existing = {
            row.source_ref
            for row in uow.connection.execute(
                text("SELECT source_ref FROM medications WHERE source=:source"),
                {"source": source},
            )
        }
        uow.connection.execute(_UPSERT, rows)
        updated = sum(row["source_ref"] in existing for row in rows)
        return len(rows) - updated, updated

    def soft_delete_missing(self, uow: UnitOfWork, source: str, refs: set[str]) -> None:
        if not refs:
            return
        uow.connection.execute(
            text(
                "UPDATE medications SET deleted_at=now() "
                "WHERE source=:source AND source_ref != ALL(:refs) AND deleted_at IS NULL"
            ),
            {"source": source, "refs": list(refs)},
        )

    def finish_run(
        self, uow: UnitOfWork, run_id: int, *, inserted: int, updated: int, failed: int
    ) -> None:
        uow.connection.execute(
            text(
                "UPDATE catalog_sync_runs SET status='thanh_cong', finished_at=now(), "
                "records_inserted=:inserted, records_updated=:updated, records_failed=:failed "
                "WHERE id=:id"
            ),
            {"id": run_id, "inserted": inserted, "updated": updated, "failed": failed},
        )

    def fail_run(self, uow: UnitOfWork, run_id: int, error: str) -> None:
        uow.connection.execute(
            text(
                "UPDATE catalog_sync_runs SET status='that_bai', finished_at=now(), "
                "error_details=jsonb_build_object('message', :error) WHERE id=:id"
            ),
            {"id": run_id, "error": error[:2000]},
        )
