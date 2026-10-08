"""Integration coverage for catalog scheduling concurrency and redelivery."""

import json
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import text

from drugtime.modules.catalog.repository import CatalogSyncRepository
from drugtime.modules.catalog.service import run_sync
from drugtime.shared.db import SqlUnitOfWork

SOURCE = "dav_drugbank"


@contextmanager
def _uow(admin_engine):
    with admin_engine.begin() as connection:
        yield SqlUnitOfWork(connection)


def _finish_running_run(admin_engine, run_id: int) -> None:
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE catalog_sync_runs "
                "SET status='that_bai', finished_at=now(), "
                "error_details=jsonb_build_object('message', 'test cleanup') "
                "WHERE id=:id AND status='dang_chay'"
            ),
            {"id": run_id},
        )


def test_only_one_running_catalog_sync_per_source__AC4(admin_engine):
    repository = CatalogSyncRepository()
    first_run_id = None

    try:
        with _uow(admin_engine) as first_uow:
            first_run_id = repository.start_run(first_uow, SOURCE, "scheduler")
        with _uow(admin_engine) as second_uow:
            second_run_id = repository.start_run(second_uow, SOURCE, "scheduler")

        assert first_run_id is not None
        assert second_run_id is None
        with admin_engine.connect() as connection:
            running_count = connection.execute(
                text(
                    "SELECT count(*) FROM catalog_sync_runs "
                    "WHERE source=:source AND status='dang_chay'"
                ),
                {"source": SOURCE},
            ).scalar_one()
        assert running_count == 1
    finally:
        if first_run_id is not None:
            _finish_running_run(admin_engine, first_run_id)


def test_catalog_redelivery_is_idempotent__AC5(admin_engine):
    source_ref = f"test-{uuid4().hex}"
    payload = json.dumps(
        {
            "result": {
                "items": [
                    {
                        "soDangKy": source_ref,
                        "tenThuoc": "Thuốc kiểm thử đồng bộ",
                        "thongTinThuocCoBan": {
                            "hoatChatChinh": "Hoạt chất thử",
                            "hamLuong": "5 mg",
                            "dangBaoChe": "Viên nén",
                            "dongGoi": "Hộp 10 viên",
                        },
                        "congTySanXuat": {
                            "tenCongTySanXuat": "Nhà sản xuất thử",
                            "nuocSanXuat": "Việt Nam",
                        },
                        "isDaRutSoDangKy": False,
                    },
                    # Một dòng không hợp lệ giữ test độc lập với dữ liệu catalog khác:
                    # service sẽ không soft-delete khi snapshot có bản ghi lỗi.
                    {"soDangKy": None, "tenThuoc": None},
                ]
            }
        }
    ).encode()

    from drugtime.modules.catalog.parsers.dav_drugbank import parse

    uow_factory = lambda: _uow(admin_engine)  # noqa: E731
    fetch = lambda: [payload]  # noqa: E731

    run_sync(uow_factory, source=SOURCE, fetch=fetch, parse=parse)
    run_sync(uow_factory, source=SOURCE, fetch=fetch, parse=parse)

    with admin_engine.connect() as connection:
        medication_count = connection.execute(
            text(
                "SELECT count(*) FROM medications "
                "WHERE source=:source AND source_ref=:source_ref"
            ),
            {"source": SOURCE, "source_ref": source_ref},
        ).scalar_one()
        running_count = connection.execute(
            text(
                "SELECT count(*) FROM catalog_sync_runs "
                "WHERE source=:source AND status='dang_chay'"
            ),
            {"source": SOURCE},
        ).scalar_one()
        successful_runs = connection.execute(
            text(
                "SELECT count(*) FROM catalog_sync_runs "
                "WHERE source=:source AND status='thanh_cong'"
            ),
            {"source": SOURCE},
        ).scalar_one()

    assert medication_count == 1
    assert running_count == 0
    assert successful_runs >= 2
