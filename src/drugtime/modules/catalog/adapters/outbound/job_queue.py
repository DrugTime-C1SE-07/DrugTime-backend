from redis import Redis
from rq import Queue

from drugtime.shared.config import get_settings

SYNC_JOB = "drugtime.runtime.job_runner.run_catalog_sync"  # chuỗi: không import runtime


def enqueue_sync(source: str | None = None) -> None:
    Queue("default", connection=Redis.from_url(get_settings().redis_url)).enqueue(SYNC_JOB, source)
