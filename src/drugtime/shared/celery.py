"""Celery client shared by the API process and worker entrypoint."""

from celery import Celery

from drugtime.shared.config import get_settings

celery_app = Celery("drugtime", broker=get_settings().celery_broker_url)
celery_app.conf.update(
    timezone=get_settings().timezone,
    task_ignore_result=True,
    task_send_sent_event=False,
    worker_send_task_events=False,
    worker_enable_remote_control=False,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_pool_limit=1,
)
