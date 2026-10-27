"""Composition root for the Celery worker and Celery Beat."""

import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Values supplied by the operating system/deployment platform take precedence.
env_file = os.getenv("DRUGTIME_ENV_FILE")
if env_file:
    load_dotenv(env_file)
else:
    load_dotenv(BACKEND_ROOT / ".env.worker.production")
    load_dotenv(BACKEND_ROOT / ".env")

from drugtime.modules.catalog import tasks as catalog_tasks  # noqa: E402,F401
from drugtime.runtime import job_runner  # noqa: E402
from drugtime.shared.celery import celery_app  # noqa: E402
from drugtime.shared.config import get_settings  # noqa: E402


# Kênh báo thiếu hoặc hỏng credential: dừng khi khởi động thay vì gửi giả (3.19).
job_runner.validate_notification_config()

celery_app.conf.beat_schedule = {
    "drugtime-periodic-tick": {
        "task": "runtime.tick",
        "schedule": float(get_settings().tick_interval_seconds),
    },
    "drugtime-worker-heartbeat": {
        "task": "runtime.heartbeat",
        "schedule": 60.0,
    },
}


@celery_app.task(name="debug.ping")
def ping(msg: str = "hello") -> None:
    print(f"[ping] {msg}")


@celery_app.task(name="runtime.tick")
def tick() -> None:
    job_runner.tick()


@celery_app.task(bind=True, name="runtime.heartbeat")
def heartbeat(self) -> None:
    job_runner.record_worker_heartbeat(self.request.hostname)


@celery_app.task(
    name="consent.erasure",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def run_erasure(request_id: str) -> None:
    job_runner.run_erasure(request_id)
