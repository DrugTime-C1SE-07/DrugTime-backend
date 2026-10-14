from contextlib import contextmanager

import pytest
from sqlalchemy import exc as sa_exc

from drugtime.modules.catalog.domain.sync_run import (
    MAX_ERROR_SAMPLES,
    CatalogSyncErrorReport,
    sanitize_error_details,
)
from drugtime.modules.catalog.normalize import NormalizedMedication
from drugtime.modules.catalog.repository import CatalogSyncRepository
from drugtime.modules.catalog.service import NoValidCatalogRecords, run_sync


@contextmanager
def fake_uow():
    yield object()


class FakeRepository:
    def __init__(self, *, write_result=(1, 0, []), fail_logging=False):
        self.write_result = write_result
        self.fail_logging = fail_logging
        self.finished = None
        self.failed = None
        self.soft_deleted = False

    def start_run(self, _uow, _source, _triggered_by):
        return 7

    def upsert_medications(self, _uow, _source, _medications):
        return self.write_result

    def soft_delete_missing(self, _uow, _source, _refs):
        self.soft_deleted = True

    def finish_run(self, _uow, _run_id, **kwargs):
        self.finished = kwargs

    def fail_run(self, _uow, _run_id, details, *, failed=0):
        if self.fail_logging:
            raise RuntimeError("logging unavailable")
        self.failed = (details, failed)


class Result:
    def __init__(self, rows=()):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class ExistingRow:
    def __init__(self, source_ref):
        self.source_ref = source_ref


class NestedTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeConnection:
    def __init__(self, *, bad_refs=(), fatal=None):
        self.bad_refs = set(bad_refs)
        self.fatal = fatal
        self.batch_failed = False

    def begin_nested(self):
        return NestedTransaction()

    def execute(self, statement, params):
        if "SELECT source_ref" in str(statement):
            return Result([ExistingRow("existing")])
        if self.fatal is not None:
            raise self.fatal
        if isinstance(params, list) and self.bad_refs:
            self.batch_failed = True
            raise sa_exc.DataError("statement", params, ValueError("bad data"))
        if isinstance(params, list):
            return Result()
        if params["source_ref"] in self.bad_refs:
            raise sa_exc.DataError("statement", params, ValueError("bad data"))
        return Result()


class FakeUow:
    def __init__(self, connection):
        self.connection = connection


def test_error_report_counts_and_caps_samples():
    report = CatalogSyncErrorReport()
    for row_number in range(1, MAX_ERROR_SAMPLES + 2):
        report.add("invalid_record", row_number, "x" * 300)

    value = report.as_json()

    assert value["groups"] == [{"code": "invalid_record", "count": 21}]
    assert len(value["samples"]) == MAX_ERROR_SAMPLES
    assert len(value["samples"][0]["source_ref"]) == 200
    assert value["samples_truncated"] is True


def test_legacy_error_details_do_not_expose_raw_message():
    value = sanitize_error_details(
        {"message": "password=secret host=private", "unexpected": "raw payload"}
    )

    assert value == {"code": "sync_failed", "message": "Catalog synchronization failed"}


def test_sanitizer_keeps_only_valid_bounded_groups_and_samples():
    value = sanitize_error_details(
        {
            "code": "invalid_record",
            "groups": [
                {"code": "invalid_record", "count": 2},
                {"code": "unknown", "count": 5},
            ],
            "samples": [
                {"row_number": 1, "code": "invalid_record", "source_ref": "ref-1"},
                {"row_number": 0, "code": "invalid_record", "source_ref": "ignored"},
            ],
        }
    )

    assert value["groups"] == [{"code": "invalid_record", "count": 2}]
    assert value["samples"] == [
        {"row_number": 1, "code": "invalid_record", "source_ref": "ref-1"}
    ]


def test_sync_keeps_valid_rows_and_reports_invalid_rows():
    repository = FakeRepository()

    run_sync(
        fake_uow,
        source="dav_drugbank",
        fetch=lambda: [b"page"],
        parse=lambda _payload: [
            {"source_ref": None, "name": None},
            {"source_ref": "ok-1", "name": "Medicine"},
        ],
        repository=repository,
    )

    assert repository.finished["inserted"] == 1
    assert repository.finished["failed"] == 1
    assert repository.finished["error_details"]["groups"] == [
        {"code": "invalid_record", "count": 1}
    ]
    assert repository.soft_deleted is False


def test_clean_snapshot_soft_deletes_missing_records():
    repository = FakeRepository()

    run_sync(
        fake_uow,
        source="dav_drugbank",
        fetch=lambda: [b"page"],
        parse=lambda _payload: [{"source_ref": "ok-1", "name": "Medicine"}],
        repository=repository,
    )

    assert repository.finished["failed"] == 0
    assert repository.finished["error_details"] is None
    assert repository.soft_deleted is True


def test_all_invalid_rows_fail_with_safe_report():
    repository = FakeRepository()

    with pytest.raises(NoValidCatalogRecords):
        run_sync(
            fake_uow,
            source="dav_drugbank",
            fetch=lambda: [b"page"],
            parse=lambda _payload: [{"source_ref": None, "name": None}],
            repository=repository,
        )

    details, failed = repository.failed
    assert failed == 1
    assert details["code"] == "no_valid_records"
    assert "password" not in str(details)


def test_database_row_error_is_counted_and_valid_row_commits():
    repository = FakeRepository(write_result=(1, 0, ["bad-1"]))

    run_sync(
        fake_uow,
        source="dav_drugbank",
        fetch=lambda: [b"page"],
        parse=lambda _payload: [
            {"source_ref": None, "name": None},
            {"source_ref": "bad-1", "name": "Bad"},
            {"source_ref": "ok-1", "name": "Good"},
        ],
        repository=repository,
    )

    assert repository.finished["failed"] == 2
    assert repository.finished["error_details"]["samples"] == [
        {"row_number": 1, "code": "invalid_record", "source_ref": None},
        {"row_number": 2, "code": "database_record_error", "source_ref": "bad-1"},
    ]


def test_failure_logging_error_preserves_original_exception():
    repository = FakeRepository(fail_logging=True)
    original = ValueError("private payload")

    with pytest.raises(ValueError) as caught:
        run_sync(
            fake_uow,
            source="dav_drugbank",
            fetch=lambda: (_ for _ in ()).throw(original),
            parse=lambda _payload: [],
            repository=repository,
        )

    assert caught.value is original


def test_repository_isolates_database_row_error_with_savepoint():
    connection = FakeConnection(bad_refs={"bad"})
    medications = [
        NormalizedMedication(source_ref="existing", name="Updated"),
        NormalizedMedication(source_ref="bad", name="Bad"),
        NormalizedMedication(source_ref="new", name="New"),
    ]

    inserted, updated, failed_refs = CatalogSyncRepository().upsert_medications(
        FakeUow(connection), "dav_drugbank", medications
    )

    assert connection.batch_failed is True
    assert (inserted, updated, failed_refs) == (1, 1, ["bad"])


def test_repository_keeps_last_duplicate_source_ref_and_counts_once():
    medications = [
        NormalizedMedication(source_ref="new", name="First"),
        NormalizedMedication(source_ref="new", name="Last"),
    ]

    inserted, updated, failed_refs = CatalogSyncRepository().upsert_medications(
        FakeUow(FakeConnection()), "dav_drugbank", medications
    )

    assert (inserted, updated, failed_refs) == (1, 0, [])


def test_repository_does_not_swallow_operational_errors():
    original = sa_exc.OperationalError("statement", {}, RuntimeError("database unavailable"))

    with pytest.raises(sa_exc.OperationalError) as caught:
        CatalogSyncRepository().upsert_medications(
            FakeUow(FakeConnection(fatal=original)),
            "dav_drugbank",
            [NormalizedMedication(source_ref="new", name="New")],
        )

    assert caught.value is original
