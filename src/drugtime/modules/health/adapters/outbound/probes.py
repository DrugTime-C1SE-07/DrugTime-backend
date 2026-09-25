from datetime import datetime

from redis import Redis
from sqlalchemy import text

from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work

WORKER_NAME = "drugtime-worker"


class LiveProbes:
    def database_ok(self) -> bool:
        try:
            with unit_of_work() as uow:
                uow.connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def redis_ok(self) -> bool:
        try:
            return bool(Redis.from_url(get_settings().redis_url, socket_timeout=2).ping())
        except Exception:
            return False

    def last_heartbeat(self) -> datetime | None:
        with unit_of_work() as uow:
            row = uow.connection.execute(
                text("SELECT last_beat_at FROM worker_heartbeats WHERE worker_name = :w"),
                {"w": WORKER_NAME},
            ).first()
        return None if row is None else row.last_beat_at


def record_heartbeat(instance_id: str) -> None:
    with unit_of_work() as uow:
        uow.connection.execute(
            text("""
            INSERT INTO worker_heartbeats (worker_name, last_beat_at, instance_id)
            VALUES (:w, now(), :i)
            ON CONFLICT (worker_name) DO UPDATE SET last_beat_at = now(),
                                                    instance_id = EXCLUDED.instance_id
        """),
            {"w": WORKER_NAME, "i": instance_id},
        )
