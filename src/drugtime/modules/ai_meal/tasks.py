"""Celery task của ai_meal (task 5.11): tìm ảnh minh họa món.

Đăng ký bằng cách import trong `drugtime/worker.py`. API đẩy job bằng `send_task` theo tên,
không import module này.
"""

from drugtime.modules.ai_meal.adapters.outbound.job_queue import FETCH_IMAGE_TASK
from drugtime.modules.ai_meal.adapters.outbound.pexels_client import PexelsClient
from drugtime.modules.ai_meal.adapters.outbound.sql_meal_images import SqlMealImages
from drugtime.modules.ai_meal.adapters.outbound.supabase_storage import SupabaseStorage
from drugtime.modules.ai_meal.application.fetch_image import fetch_image
from drugtime.shared.celery import celery_app
from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work


@celery_app.task(name=FETCH_IMAGE_TASK, acks_late=True, reject_on_worker_lost=True)
def fetch_meal_image(image_id: int) -> str:
    settings = get_settings()
    key = settings.pexels_api_key.get_secret_value()
    if not settings.ai_meal_image_enabled or not key:
        # Tắt sau khi job đã được đẩy: không gọi kho ảnh, ảnh tự thành failed sau 2 phút.
        return "disabled"
    return fetch_image(
        int(image_id),
        uow_factory=unit_of_work,
        records=SqlMealImages(),
        search=PexelsClient(api_key=key, timeout_seconds=settings.pexels_timeout_seconds),
        storage=SupabaseStorage(
            base_url=settings.supabase_url,
            service_key=settings.supabase_service_key,
            bucket=settings.ai_meal_image_bucket,
        ),
    )
