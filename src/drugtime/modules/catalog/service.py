"""Catalog synchronization orchestration."""

from collections.abc import Callable, Iterable

import httpx
from sqlalchemy.exc import OperationalError

from drugtime.modules.catalog.domain.sync_run import CatalogSyncErrorReport
from drugtime.modules.catalog.normalize import NormalizedMedication, normalize_record
from drugtime.modules.catalog.repository import CatalogSyncRepository


def run_sync(
    uow_factory,
    *,
    source: str,
    fetch: Callable[[], Iterable[bytes]],
    parse: Callable[[bytes], list[dict[str, object]]],
    triggered_by: str = "scheduler",
    repository: CatalogSyncRepository | None = None,
) -> None:
    repository = repository or CatalogSyncRepository()
    with uow_factory() as uow:
        run_id = repository.start_run(uow, source, triggered_by)
    if run_id is None:
        return

    try:
        normalized: list[NormalizedMedication] = []
        source_positions: dict[str, int] = {}
        report = CatalogSyncErrorReport()
        row_number = 0
        for payload in fetch():
            for row in parse(payload):
                row_number += 1
                try:
                    item = normalize_record(row)
                    normalized.append(item)
                    source_positions[item.source_ref] = row_number
                except ValueError:
                    report.add("invalid_record", row_number, row.get("source_ref"))

        if not normalized:
            raise NoValidCatalogRecords(report)

        with uow_factory() as uow:
            inserted, updated, failed_refs = repository.upsert_medications(uow, source, normalized)
            for source_ref in failed_refs:
                report.add(
                    "database_record_error", source_positions.get(source_ref, 1), source_ref
                )
            if inserted + updated == 0:
                raise NoValidCatalogRecords(report)
            if report.total == 0:
                repository.soft_delete_missing(
                    uow, source, {item.source_ref for item in normalized}
                )
            repository.finish_run(
                uow,
                run_id,
                inserted=inserted,
                updated=updated,
                failed=report.total,
                error_details=report.as_json(),
            )
    except Exception as exc:
        details, failed = _failure_details(exc)
        try:
            with uow_factory() as uow:
                repository.fail_run(uow, run_id, details, failed=failed)
        except Exception:
            # Preserve the original error so Celery applies the correct retry policy.
            exc.add_note("catalog sync failure could not be persisted")
        raise


class NoValidCatalogRecords(ValueError):
    def __init__(self, report: CatalogSyncErrorReport) -> None:
        super().__init__("catalog source returned no valid records")
        self.report = report


def _failure_details(exc: Exception) -> tuple[dict, int]:
    if isinstance(exc, NoValidCatalogRecords):
        return exc.report.as_json("no_valid_records") or {}, exc.report.total
    if isinstance(exc, (httpx.TimeoutException,)):
        return CatalogSyncErrorReport().as_json("source_timeout") or {}, 0
    if isinstance(exc, (httpx.TransportError, httpx.HTTPStatusError)):
        return CatalogSyncErrorReport().as_json("source_unavailable") or {}, 0
    if isinstance(exc, OperationalError):
        return CatalogSyncErrorReport().as_json("database_unavailable") or {}, 0
    if isinstance(exc, (ValueError, TypeError)):
        return CatalogSyncErrorReport().as_json("invalid_payload") or {}, 0
    return CatalogSyncErrorReport().as_json("sync_failed") or {}, 0
