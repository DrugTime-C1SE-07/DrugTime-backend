"""POST /patients/{patient_id}/meal-suggestions (PB37, task 4.26; luồng DK6).

access(goi_y_bua_an) → medication + interaction (tất định) → LLM → lọc món → lưu + disclaimer
do backend gắn. Lỗi LLM được trả từ bên trong transaction để dòng access_logs `allowed` vẫn
commit (dữ liệu sức khỏe đã được đọc); lỗi DB hoặc ghi log làm rollback, không trả gợi ý.
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
from drugtime.modules.ai_meal.adapters.outbound.other_modules import (
    InteractionFoodCheck,
    MedicationConditions,
)
from drugtime.modules.ai_meal.adapters.outbound.sql_meal_suggestions import SqlMealSuggestions
from drugtime.modules.ai_meal.application.ports import MealSuggester
from drugtime.modules.ai_meal.application.suggest_meals import (
    MealOutcome,
    MealRequest,
    suggest_meals,
)
from drugtime.modules.ai_meal.domain.errors import LlmDisabled, LlmInvalidOutput, LlmUnavailable
from drugtime.modules.ai_meal.domain.model import MEAL_DISCLAIMER, DietaryDeclaration
from drugtime.modules.identity import api as identity
from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work

router = APIRouter(tags=["ai_meal"])
_log = logging.getLogger(__name__)

# Đăng ký với tests/architecture/test_health_route_enforcement.py (task 4.26).
_HEALTH_EXTRA = {"x-health-scope": "goi_y_bua_an", "x-health-audit-self": True}
# Chỉ để OpenAPI khai báo `security: bearerAuth`; xác thực thật ở identity.current_user_short_uow.
_BEARER = Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
_NO_STORE = {"Cache-Control": "no-store"}
_NO_STORE_DOC = {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}


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


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=_NO_STORE)


def _payload(outcome: MealOutcome) -> dict:
    return MealSuggestionResponse.model_validate(
        {
            "suggestion_id": outcome.suggestion_id,
            "meal_type": outcome.result.meal_type.value,
            "suggestions": [asdict(s) for s in outcome.result.suggestions],
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
            "created_at": outcome.created_at,
        }
    ).model_dump(mode="json")


@router.post(
    "/patients/{patient_id}/meal-suggestions",
    response_model=MealSuggestionResponse,
    responses={
        200: {"headers": _NO_STORE_DOC},
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        403: {"model": ErrorDetail, "description": "khong_co_quyen | consent_revoked"},
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
    user: Annotated[identity.CurrentUser, Depends(identity.current_user_short_uow)],
    suggester: Annotated[MealSuggester | None, Depends(get_meal_suggester)],
) -> JSONResponse:
    request = MealRequest(
        meal_type=body.meal_type,
        allergies=DietaryDeclaration(body.allergies.none, tuple(body.allergies.items)),
        dietary_restrictions=DietaryDeclaration(
            body.dietary_restrictions.none, tuple(body.dietary_restrictions.items)
        ),
        preferences=tuple(body.preferences),
    )
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
                )
            except LlmDisabled:
                response = _error(503, "llm_disabled")
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
        response = _error(503, "service_unavailable")
    return response
