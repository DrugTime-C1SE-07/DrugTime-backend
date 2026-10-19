"""SQL persistence for catalog synchronization."""

import json
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import exc as sa_exc
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
    ) -> tuple[int, int, list[str]]:
        rows_by_ref = {
            item.source_ref: {**asdict(item), "source": source} for item in medications
        }
        rows = list(rows_by_ref.values())
        if not rows:
            return 0, 0, []

        existing = {
            row.source_ref
            for row in uow.connection.execute(
                text("SELECT source_ref FROM medications WHERE source=:source"),
                {"source": source},
            )
        }
        try:
            with uow.connection.begin_nested():
                uow.connection.execute(_UPSERT, rows)
        except (sa_exc.IntegrityError, sa_exc.DataError):
            inserted = updated = 0
            failed_refs: list[str] = []
            for row in rows:
                try:
                    with uow.connection.begin_nested():
                        uow.connection.execute(_UPSERT, row)
                except (sa_exc.IntegrityError, sa_exc.DataError):
                    failed_refs.append(str(row["source_ref"]))
                    continue
                if row["source_ref"] in existing:
                    updated += 1
                else:
                    inserted += 1
                    existing.add(row["source_ref"])
            return inserted, updated, failed_refs

        updated = 0
        for row in rows:
            if row["source_ref"] in existing:
                updated += 1
            else:
                existing.add(row["source_ref"])
        return len(rows) - updated, updated, []

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
        self,
        uow: UnitOfWork,
        run_id: int,
        *,
        inserted: int,
        updated: int,
        failed: int,
        error_details: dict | None = None,
    ) -> None:
        uow.connection.execute(
            text(
                "UPDATE catalog_sync_runs SET status='thanh_cong', finished_at=now(), "
                "records_inserted=:inserted, records_updated=:updated, records_failed=:failed, "
                "error_details=CAST(:error_details AS jsonb) "
                "WHERE id=:id"
            ),
            {
                "id": run_id,
                "inserted": inserted,
                "updated": updated,
                "failed": failed,
                "error_details": None if error_details is None else json.dumps(error_details),
            },
        )

    def fail_run(
        self,
        uow: UnitOfWork,
        run_id: int,
        error_details: dict,
        *,
        failed: int = 0,
    ) -> None:
        uow.connection.execute(
            text(
                "UPDATE catalog_sync_runs SET status='that_bai', finished_at=now(), "
                "records_inserted=0, records_updated=0, records_failed=:failed, "
                "error_details=CAST(:error_details AS jsonb) WHERE id=:id"
            ),
            {"id": run_id, "failed": failed, "error_details": json.dumps(error_details)},
        )
