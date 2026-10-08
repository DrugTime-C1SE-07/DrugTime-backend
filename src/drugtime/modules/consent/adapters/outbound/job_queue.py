"""Celery producer for consent background tasks."""

from uuid import UUID

from drugtime.shared.celery import celery_app


ERASURE_TASK = "consent.erasure"


def enqueue_erasure(request_id: UUID) -> str:
    result = celery_app.send_task(ERASURE_TASK, args=[str(request_id)])
    return result.id
