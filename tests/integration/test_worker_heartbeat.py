"""Task 3.19 (AC46): heartbeat của Worker ghi bằng worker_role và /health/ready thấy được."""

from contextlib import contextmanager

from sqlalchemy import text

from drugtime.modules.health.adapters.outbound import probes
from drugtime.runtime import job_runner
from drugtime.shared.db import SqlUnitOfWork


def test_heartbeat_row_and_ready__AC46(db, client, role_engines, monkeypatch):
    @contextmanager
    def worker_uow():
        with role_engines["worker_role"].begin() as connection:
            yield SqlUnitOfWork(connection)

    before = db.execute(text("SELECT clock_timestamp()")).scalar_one()
    # Worker thật chạy với DATABASE_URL của worker_role; ở đây thay unit_of_work tương ứng.
    monkeypatch.setattr(probes, "unit_of_work", worker_uow)
    job_runner.record_worker_heartbeat("it-3.19")
    monkeypatch.undo()

    row = db.execute(
        text("SELECT last_beat_at, instance_id FROM worker_heartbeats WHERE worker_name = :w"),
        {"w": probes.WORKER_NAME},
    ).one()
    assert row.instance_id == "it-3.19" and row.last_beat_at >= before

    # API (api_role) đọc heartbeat; Redis có thể không chạy ở máy dev nên chỉ kiểm mục heartbeat.
    body = client.get("/health/ready").json()
    assert body["database"] is True and body["worker_heartbeat"] is True
