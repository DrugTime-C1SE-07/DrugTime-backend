"""Component Scheduler (CD10).

rq-scheduler lưu lịch trong Redis. Vòng lặp ở đây chạy trong tiến trình Worker, mỗi phút
đăng ký lại tick nếu mất (Redis mất dữ liệu) và ghi heartbeat. Lịch vì thế luôn khôi phục
được từ code, không phụ thuộc trạng thái của Redis.
"""

import logging
import threading
from datetime import UTC, datetime

from redis import Redis
from rq_scheduler import Scheduler

from drugtime.modules.health import api as health
from drugtime.shared.config import get_settings

log = logging.getLogger(__name__)

TICK_JOB_ID = "drugtime-tick"  # RQ 2.x: chỉ chữ, số, "_" và "-"
TICK_FUNC = "drugtime.runtime.job_runner.tick"
LOOP_SECONDS = 60


def ensure_schedules(redis: Redis) -> bool:
    """Đăng ký tick nếu chưa có. Trả True nếu vừa đăng ký. Idempotent (job id cố định)."""
    scheduler = Scheduler(queue_name="default", connection=redis)
    if any(job.id == TICK_JOB_ID for job in scheduler.get_jobs()):
        return False
    scheduler.schedule(
        scheduled_time=datetime.now(UTC),
        func=TICK_FUNC,
        interval=get_settings().tick_interval_seconds,
        repeat=None,
        id=TICK_JOB_ID,
        queue_name="default",
    )
    log.warning("tick schedule was missing and has been re-registered")
    return True


def run_loop(redis: Redis, instance_id: str, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            ensure_schedules(redis)
        except Exception:
            log.exception("ensure_schedules failed")
        try:
            health.record_heartbeat(instance_id)
        except Exception:
            log.exception("heartbeat failed")
        stop.wait(LOOP_SECONDS)
