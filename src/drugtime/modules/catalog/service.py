"""Catalog synchronization orchestration."""

from collections.abc import Callable, Iterable

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
        failed = 0
        for payload in fetch():
            for row in parse(payload):
                try:
                    normalized.append(normalize_record(row))
                except ValueError:
                    failed += 1

        if not normalized:
            raise ValueError("DAV returned no valid medication records")

        with uow_factory() as uow:
            inserted, updated = repository.upsert_medications(uow, source, normalized)
            if failed == 0:
                repository.soft_delete_missing(
                    uow, source, {item.source_ref for item in normalized}
                )
            repository.finish_run(
                uow, run_id, inserted=inserted, updated=updated, failed=failed
            )
    except Exception as exc:
        with uow_factory() as uow:
            repository.fail_run(uow, run_id, str(exc))
        raise
