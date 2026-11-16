"""POST /patients/{patient_id}/meal-suggestions (PB37, task 4.26; gợi ý lại + ảnh: task 5.11).

access(goi_y_bua_an) → medication + interaction (tất định) → LLM → lọc món → lưu + disclaimer
do backend gắn. Lỗi LLM, 422 `previous_suggestion_not_found` và 429 được trả từ bên trong
transaction để dòng access_logs `allowed` vẫn commit (dữ liệu sức khỏe đã được đọc); lỗi DB hoặc
ghi log làm rollback, không trả gợi ý. Job ảnh chỉ được đẩy sau khi transaction commit.
"""

import logging
from dataclasses import asdict
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from drugtime.modules.ai_meal.adapters.inbound.schemas import (
    ErrorDetail,
    MealSuggestionRequest,
    MealSuggestionResponse,
)
from drugtime.modules.ai_meal.adapters.outbound.claude_suggester import ClaudeMealSuggester
from drugtime.modules.ai_meal.adapters.outbound.job_queue import CeleryImageJobQueue
from drugtime.modules.ai_meal.adapters.outbound.other_modules import (
    InteractionFoodCheck,
    MedicationConditions,
)
from drugtime.modules.ai_meal.adapters.outbound.sql_meal_images import SqlMealImages
from drugtime.modules.ai_meal.adapters.outbound.sql_meal_suggestions import SqlMealSuggestions
from drugtime.modules.ai_meal.application.ports import (
    ImageJobQueue,
    ImageState,
    MealImageStore,
    MealSuggester,
)
from drugtime.modules.ai_meal.application.suggest_meals import (
    MealOutcome,
    MealRequest,
    suggest_meals,
)
from drugtime.modules.ai_meal.domain.errors import (
    LlmDisabled,
    LlmInvalidOutput,
    LlmUnavailable,
    PreviousSuggestionNotFound,
    RefreshLimitReached,
)
from drugtime.modules.ai_meal.domain.model import MEAL_DISCLAIMER, DietaryDeclaration
from drugtime.modules.identity import api as identity
from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work

router = APIRouter(tags=["ai_meal"])
_log = logging.getLogger(__name__)

# Đăng ký với tests/architecture/test_health_route_enforcement.py (task 4.26).
_HEALTH_EXTRA = {"x-health-scope": "goi_y_bua_an", "x-health-audit-self": True}
# Chỉ để OpenAPI khai báo `security: bearerAuth`; xác thực thật ở identity.current_user.
_BEARER = Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
_NO_STORE = {"Cache-Control": "no-store"}
_NO_STORE_DOC = {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}
IMAGE_PATH = "/meal-images/{image_id}"


@lru_cache(maxsize=4)
def _claude(api_key: str, model: str, timeout: float, base_url: str) -> ClaudeMealSuggester:
    return ClaudeMealSuggester(
        api_key=api_key, model=model, timeout_seconds=timeout, base_url=base_url or None
    )


def get_meal_suggester() -> MealSuggester | None:
    """None khi tính năng tắt hoặc thiếu key (AC10). Test tích hợp override dependency này."""
    settings = get_settings()
    key = settings.llm_api_key.get_secret_value()
    if not settings.ai_meal_llm_enabled or not key:
        return None
    return _claude(key, settings.llm_model, settings.llm_timeout_seconds, settings.llm_api_url)


def get_meal_images() -> MealImageStore | None:
    """None khi tính năng ảnh tắt (5.11 AC8): không giữ chỗ, không đẩy job, món không có ảnh."""
    return SqlMealImages() if get_settings().ai_meal_image_enabled else None


def get_image_queue() -> ImageJobQueue:
    """Test override để không cần broker."""
    return CeleryImageJobQueue()


def get_refresh_limit() -> int:
    return get_settings().ai_meal_refresh_daily_limit


def _error(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        {"detail": detail}, status_code=status, headers={**_NO_STORE, **(headers or {})}
    )


def image_payload(image_id: int, state: ImageState) -> dict:
    ready = state.status == "ready"
    return {
        "image_id": image_id,
        "status": state.status,
        "url": IMAGE_PATH.format(image_id=image_id) if ready else None,
        "attribution": {
            "provider": "pexels",
            "photographer_name": state.photographer_name,
            "photographer_url": state.photographer_url,
            "source_url": state.source_url,
        }
        if ready
        else None,
    }


def _payload(outcome: MealOutcome) -> dict:
    states = outcome.images or {}
    suggestions = []
    for s in outcome.result.suggestions:
        dish = asdict(s)
        dish.pop("image_query")  # nội bộ, không bao giờ trả client (AC9)
        image_id = dish.pop("image_id")
        dish["image"] = (
            image_payload(image_id, states[image_id])
            if image_id is not None and image_id in states
            else None
        )
        suggestions.append(dish)
    return MealSuggestionResponse.model_validate(
        {
            "suggestion_id": outcome.suggestion_id,
            "meal_type": outcome.result.meal_type.value,
            "suggestions": suggestions,
            "food_check": {
                "status": outcome.food.status,
                "warnings": [
                    {
                        "rule_id": w.rule_id,
                        "version_id": w.version_id,
                        "ingredient": {"id": w.ingredient_id, "standard_name": w.ingredient_name},
                        "food_to_avoid": w.food_to_avoid,
                        "severity_level": w.severity_level,
                        "reason": w.reason,
                        "source": w.source,
                    }
                    for w in outcome.food.warnings
                ],
            },
            "disclaimer": MEAL_DISCLAIMER,
            "refreshes_remaining": outcome.refreshes_remaining,
            "created_at": outcome.created_at,
        }
    ).model_dump(mode="json")


def _enqueue(queue: ImageJobQueue, image_ids: tuple[int, ...]) -> None:
    """Sau commit. Broker lỗi không làm hỏng gợi ý: ảnh thành `failed` sau 2 phút."""
    for image_id in image_ids:
        try:
            queue.enqueue(image_id)
        except Exception as exc:  # noqa: BLE001 — mọi lỗi broker; chỉ log loại lỗi
            _log.warning(
                "ai_meal image_enqueue_failed id=%s error=%s", image_id, type(exc).__name__
            )


@router.post(
    "/patients/{patient_id}/meal-suggestions",
    response_model=MealSuggestionResponse,
    responses={
        200: {"headers": _NO_STORE_DOC},
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        403: {"model": ErrorDetail, "description": "khong_co_quyen | consent_revoked"},
        422: {"description": "ValidationError | previous_suggestion_not_found"},
        429: {
            "model": ErrorDetail,
            "description": "refresh_limit_reached",
            "headers": {**_NO_STORE_DOC, "Retry-After": {"schema": {"type": "integer"}}},
        },
        502: {"model": ErrorDetail, "description": "llm_invalid_output", "headers": _NO_STORE_DOC},
        503: {
            "model": ErrorDetail,
            "description": "llm_disabled | llm_unavailable | service_unavailable",
            "headers": _NO_STORE_DOC,
        },
    },
    operation_id="createMealSuggestions",
    summary="Gợi ý bữa ăn bằng AI cho người bệnh (PB37, Task 4.26)",
    openapi_extra=_HEALTH_EXTRA,
    dependencies=[_BEARER],
)
def create_meal_suggestions_endpoint(
    patient_id: UUID,
    body: MealSuggestionRequest,
    user: Annotated[identity.CurrentUser, Depends(identity.current_user)],
    suggester: Annotated[MealSuggester | None, Depends(get_meal_suggester)],
    images: Annotated[MealImageStore | None, Depends(get_meal_images)],
    queue: Annotated[ImageJobQueue, Depends(get_image_queue)],
    refresh_limit: Annotated[int, Depends(get_refresh_limit)],
) -> JSONResponse:
    request = MealRequest(
        meal_type=body.meal_type,
        allergies=DietaryDeclaration(body.allergies.none, tuple(body.allergies.items)),
        dietary_restrictions=DietaryDeclaration(
            body.dietary_restrictions.none, tuple(body.dietary_restrictions.items)
        ),
        preferences=tuple(body.preferences),
        previous_suggestion_id=body.previous_suggestion_id,
    )
    outcome: MealOutcome | None = None
    try:
        with unit_of_work() as uow:
            try:
                outcome = suggest_meals(
                    uow,
                    caller_id=user.id,
                    caller_is_admin=user.is_admin,
                    patient_id=patient_id,
                    request=request,
                    suggester=suggester,
                    food=InteractionFoodCheck(),
                    conditions=MedicationConditions(),
                    store=SqlMealSuggestions(),
                    images=images,
                    refresh_limit=refresh_limit,
                )
            except LlmDisabled:
                response = _error(503, "llm_disabled")
            except PreviousSuggestionNotFound:
                response = _error(422, "previous_suggestion_not_found")
            except RefreshLimitReached as exc:
                response = _error(
                    429, "refresh_limit_reached", {"Retry-After": str(exc.retry_after)}
                )
            except LlmUnavailable as exc:
                # Chỉ mã lý do; không bao giờ log prompt, output hay dữ liệu sức khỏe (AC18).
                _log.warning("ai_meal llm_failure kind=unavailable reason=%s", exc.reason)
                response = _error(503, "llm_unavailable")
            except LlmInvalidOutput as exc:
                _log.warning("ai_meal llm_failure kind=invalid_output reason=%s", exc.reason)
                response = _error(502, "llm_invalid_output")
            else:
                # Dựng response trong transaction: access_logs + meal_suggestions commit trước.
                response = JSONResponse(_payload(outcome), headers=_NO_STORE)
    except SQLAlchemyError:
        # CSDL hoặc ghi access_logs lỗi (kể cả lúc commit): transaction đã rollback, không trả
        # gợi ý (fail-closed). Không log nội dung lỗi hay tham số SQL (dữ liệu sức khỏe).
        _log.warning("ai_meal db_failure")
        return _error(503, "service_unavailable")
    if outcome is not None:
        _enqueue(queue, outcome.enqueue_image_ids)
    return response
