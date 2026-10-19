"""Integration coverage for catalog sync run lifecycle and transaction safety."""

from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from tests.integration.conftest import ADMIN_URL

from drugtime.modules.catalog.repository import CatalogSyncRepository
from drugtime.modules.catalog.service import NoValidCatalogRecords, run_sync
from drugtime.shared.db import SqlUnitOfWork

SOURCE = "qd_5948"


@contextmanager
def _uow(engine):
    with engine.begin() as connection:
        yield SqlUnitOfWork(connection)


@pytest.fixture
def transactional_engine(admin_engine):
    engine = create_engine(ADMIN_URL)
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE catalog_sync_runs SET status='that_bai', finished_at=now(), "
                "error_details=CAST(:details AS jsonb) "
                "WHERE source=CAST(:source AS catalog_source) AND status='dang_chay'"
            ),
            {"source": SOURCE, "details": '{"code":"sync_failed"}'},
        )
    yield engine
    engine.dispose()


def _run_row(admin_engine, run_id):
    with admin_engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT status::text AS status, started_at, finished_at, records_inserted, "
                "records_updated, records_failed, error_details FROM catalog_sync_runs "
                "WHERE id=:id"
            ),
            {"id": run_id},
        ).one()


def _latest_run_id(admin_engine):
    with admin_engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT coalesce(max(id), 0) FROM catalog_sync_runs "
                "WHERE source=CAST(:source AS catalog_source)"
            ),
            {"source": SOURCE},
        ).scalar_one()


def test_row_errors_continue_and_are_reconciled__AC1_AC2_AC3_AC10(
    admin_engine, transactional_engine
):
    existing_ref = f"existing-{uuid4().hex}"
    valid_ref = f"valid-{uuid4().hex}"
    bad_ref = f"bad-{uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO medications (name, source, source_ref) "
                "VALUES ('Existing', CAST(:source AS catalog_source), :ref)"
            ),
            {"source": SOURCE, "ref": existing_ref},
        )

    run_sync(
        lambda: _uow(transactional_engine),
        source=SOURCE,
        fetch=lambda: [b"page"],
        parse=lambda _payload: [
            {"source_ref": valid_ref, "name": "Valid medicine"},
            {"source_ref": None, "name": None},
            {"source_ref": bad_ref, "name": "bad\x00name"},
        ],
    )

    run = _run_row(admin_engine, _latest_run_id(admin_engine))
    assert run.status == "thanh_cong"
    assert run.finished_at >= run.started_at
    assert (run.records_inserted, run.records_updated, run.records_failed) == (1, 0, 2)
    assert run.error_details["groups"] == [
        {"code": "database_record_error", "count": 1},
        {"code": "invalid_record", "count": 1},
    ]
    assert run.error_details["samples"] == [
        {"row_number": 2, "code": "invalid_record", "source_ref": None},
        {"row_number": 3, "code": "database_record_error", "source_ref": bad_ref},
    ]
    with admin_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT source_ref, deleted_at FROM medications "
                "WHERE source=CAST(:source AS catalog_source) AND source_ref=ANY(:refs)"
            ),
            {"source": SOURCE, "refs": [existing_ref, valid_ref, bad_ref]},
        ).all()
    assert {row.source_ref for row in rows} == {existing_ref, valid_ref}
    assert next(row for row in rows if row.source_ref == existing_ref).deleted_at is None


class FailAfterWriteRepository(CatalogSyncRepository):
    def finish_run(self, *_args, **_kwargs):
        raise RuntimeError("forced failure after data write")


def test_fatal_failure_rolls_back_data_and_logs_failure__AC5(admin_engine, transactional_engine):
    source_ref = f"rollback-{uuid4().hex}"

    with pytest.raises(RuntimeError, match="forced failure"):
        run_sync(
            lambda: _uow(transactional_engine),
            source=SOURCE,
            fetch=lambda: [b"page"],
            parse=lambda _payload: [{"source_ref": source_ref, "name": "Rollback medicine"}],
            repository=FailAfterWriteRepository(),
        )

    run = _run_row(admin_engine, _latest_run_id(admin_engine))
    assert run.status == "that_bai"
    assert run.finished_at >= run.started_at
    assert (run.records_inserted, run.records_updated) == (0, 0)
    assert run.error_details == {
        "code": "sync_failed",
        "message": "Catalog synchronization failed",
    }
    with admin_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM medications WHERE source_ref=:ref"),
            {"ref": source_ref},
        ).scalar_one()
    assert count == 0


def test_all_invalid_rows_are_logged_as_failed__AC6(admin_engine, transactional_engine):
    with pytest.raises(NoValidCatalogRecords):
        run_sync(
            lambda: _uow(transactional_engine),
            source=SOURCE,
            fetch=lambda: [b"page"],
            parse=lambda _payload: [{"source_ref": None, "name": None}],
        )

    run = _run_row(admin_engine, _latest_run_id(admin_engine))
    assert run.status == "that_bai"
    assert run.records_failed == 1
    assert run.error_details["code"] == "no_valid_records"


def test_retry_attempts_create_separate_failed_runs__AC4(admin_engine, transactional_engine):
    before = _latest_run_id(admin_engine)

    def fail_fetch():
        request = httpx.Request("GET", "https://catalog.invalid")
        raise httpx.ConnectError("private source detail", request=request)

    for _ in range(2):
        with pytest.raises(httpx.ConnectError):
            run_sync(
                lambda: _uow(transactional_engine),
                source=SOURCE,
                fetch=fail_fetch,
                parse=lambda _payload: [],
            )

    with admin_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT status::text AS status, error_details FROM catalog_sync_runs "
                "WHERE source=CAST(:source AS catalog_source) AND id>:before ORDER BY id"
            ),
            {"source": SOURCE, "before": before},
        ).all()
    assert len(rows) == 2
    assert all(row.status == "that_bai" for row in rows)
    assert all(row.error_details["code"] == "source_unavailable" for row in rows)
    assert "private" not in str([row.error_details for row in rows])
