from uuid import UUID

from redis import Redis
from rq import Queue

from drugtime.shared.config import get_settings

# Tham chiếu job bằng chuỗi để consent không import drugtime.runtime (contract import-linter).
ERASURE_JOB = "drugtime.runtime.job_runner.run_erasure"


def enqueue_erasure(request_id: UUID) -> None:
    queue = Queue("default", connection=Redis.from_url(get_settings().redis_url))
    queue.enqueue(ERASURE_JOB, str(request_id))
