"""GET /meal-images và GET /meal-images/{image_id} (task 5.11, contract mục 3.2, 3.3).

Không phải route dữ liệu sức khỏe: không có `x-health-scope`, không qua PEP, không ghi
access_logs. Chỉ cần phiên đăng nhập hợp lệ (identity.current_user). Ảnh đọc từ kho lưu trữ
bằng service key phía server; client không bao giờ có key hay URL kho lưu trữ (bất biến 1).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from drugtime.modules.ai_meal.adapters.inbound.http import image_payload
from drugtime.modules.ai_meal.adapters.inbound.schemas import ErrorDetail, MealImageStatusList
from drugtime.modules.ai_meal.adapters.outbound.sql_meal_images import SqlMealImages
from drugtime.modules.ai_meal.adapters.outbound.supabase_storage import SupabaseStorage
from drugtime.modules.ai_meal.application.meal_images import (
    list_image_states,
    read_image,
    read_image_meta,
)
from drugtime.modules.ai_meal.application.ports import ImageStorage, MealImageStore
from drugtime.modules.ai_meal.domain.errors import MealImageNotFound, StorageUnavailable
from drugtime.modules.identity import api as identity
from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work

router = APIRouter(tags=["ai_meal"])
_log = logging.getLogger(__name__)

_BEARER = Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
_NO_STORE = {"Cache-Control": "no-store"}
_NO_STORE_DOC = {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}
IMMUTABLE = "private, max-age=2592000, immutable"
_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


def get_image_store() -> MealImageStore:
    return SqlMealImages()


def get_image_storage() -> ImageStorage:
    s = get_settings()
    return SupabaseStorage(
        base_url=s.supabase_url, service_key=s.supabase_service_key, bucket=s.ai_meal_image_bucket
    )


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=_NO_STORE)


@router.get(
    "/meal-images",
    response_model=MealImageStatusList,
    responses={
        200: {"headers": _NO_STORE_DOC},
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        503: {"model": ErrorDetail, "description": "service_unavailable", "headers": _NO_STORE_DOC},
    },
    operation_id="listMealImageStatuses",
    summary="Đọc trạng thái ảnh minh họa món ăn (task 5.11)",
    dependencies=[_BEARER],
)
def list_meal_images_endpoint(
    ids: Annotated[list[Annotated[int, Field(ge=1)]], Query(min_length=1, max_length=20)],
    user: Annotated[identity.CurrentUser, Depends(identity.current_user)],
    store: Annotated[MealImageStore, Depends(get_image_store)],
) -> JSONResponse:
    del user  # chỉ cần phiên hợp lệ
    if len(set(ids)) != len(ids):
        return JSONResponse(
            {"detail": [{"loc": ["query", "ids"], "msg": "ids must be unique",
                         "type": "value_error"}]},
            status_code=422,
        )
    try:
        with unit_of_work() as uow:
            states = list_image_states(uow, store, ids)
    except SQLAlchemyError:
        _log.warning("ai_meal image_db_failure")
        return _error(503, "service_unavailable")
    body = MealImageStatusList.model_validate(
        {"items": [image_payload(s.image_id, s) for s in states]}
    ).model_dump(mode="json")
    return JSONResponse(body, headers=_NO_STORE)


@router.get(
    "/meal-images/{image_id}",
    response_class=Response,
    responses={
        200: {
            "description": "Nội dung ảnh",
            "content": {t: {"schema": {"type": "string", "contentMediaType": t}}
                        for t in _IMAGE_TYPES},
            "headers": {"Cache-Control": {"schema": {"type": "string", "const": IMMUTABLE}}},
        },
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        404: {"model": ErrorDetail, "description": "meal_image_not_found",
              "headers": _NO_STORE_DOC},
        503: {"model": ErrorDetail, "description": "service_unavailable", "headers": _NO_STORE_DOC},
    },
    operation_id="getMealImage",
    summary="Tải ảnh minh họa món ăn (task 5.11)",
    dependencies=[_BEARER],
)
def get_meal_image_endpoint(
    image_id: Annotated[int, Path(ge=1)],
    user: Annotated[identity.CurrentUser, Depends(identity.current_user)],
    store: Annotated[MealImageStore, Depends(get_image_store)],
    storage: Annotated[ImageStorage, Depends(get_image_storage)],
) -> Response:
    del user
    try:
        with unit_of_work() as uow:
            state = read_image_meta(uow, store, image_id)
    except MealImageNotFound:
        return _error(404, "meal_image_not_found")
    except SQLAlchemyError:
        _log.warning("ai_meal image_db_failure")
        return _error(503, "service_unavailable")
    try:
        image = read_image(storage, state)
    except StorageUnavailable as exc:
        _log.warning("ai_meal image_storage_failure id=%s reason=%s", image_id, exc.reason)
        return _error(503, "service_unavailable")
    return Response(
        content=image.content, media_type=image.content_type, headers={"Cache-Control": IMMUTABLE}
    )
