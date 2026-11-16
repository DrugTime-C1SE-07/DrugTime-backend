"""Celery producer cho job ảnh món (task 5.11). Chỉ đẩy theo tên task, không import Worker."""

from drugtime.shared.celery import celery_app

FETCH_IMAGE_TASK = "ai_meal.fetch_image"


class CeleryImageJobQueue:
    def enqueue(self, image_id: int) -> None:
        celery_app.send_task(FETCH_IMAGE_TASK, args=[image_id])
