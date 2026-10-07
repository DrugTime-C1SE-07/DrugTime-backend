"""Celery producer for catalog background tasks."""

from drugtime.shared.celery import celery_app

SYNC_TASK = "catalog.sync"


def enqueue_sync(
    source: str | None = None,
    *,
    triggered_by: str = "admin_thu_cong",
) -> str:
    """Enqueue without importing the worker composition root."""
    result = celery_app.send_task(
        SYNC_TASK,
        args=[source],
        kwargs={"triggered_by": triggered_by},
    )
    return result.id
