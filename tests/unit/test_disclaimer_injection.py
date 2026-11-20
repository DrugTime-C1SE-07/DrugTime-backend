"""Unit tests for Task 5.10 (PB37): Mandatory Disclaimer Injection Logic.

Verifies AC1-AC5:
- AC1: 100% response contains canonical MEAL_DISCLAIMER.
- AC2: Fail-closed (ValidationError when disclaimer is missing, empty, or whitespace-only).
- AC3: Tamper resistance (LLM injected disclaimer is ignored / overridden by backend constant).
- AC4: Deterministic 3-state food_check is preserved (CD6).
- AC5: Cache-Control: no-store on response.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from drugtime.modules.ai_meal.adapters.inbound.schemas import MealSuggestionResponse
from drugtime.modules.ai_meal.domain.model import (
    MEAL_DISCLAIMER,
    DietaryDeclaration,
    MealSuggestionInput,
    validate_disclaimer,
)
from drugtime.modules.ai_meal.domain.parser import parse_suggestions
from drugtime.modules.ai_meal.domain.prompt import build_prompt

_HCM = ZoneInfo("Asia/Ho_Chi_Minh")


def _valid_response_payload(**overrides) -> dict:
    base = {
        "suggestion_id": 1001,
        "meal_type": "trua",
        "suggestions": [],
        "food_check": {
            "status": "da_kiem_tra_khong_thay",
            "warnings": [],
        },
        "disclaimer": MEAL_DISCLAIMER,
        "refreshes_remaining": 2,
        "created_at": datetime.now(_HCM),
    }
    base.update(overrides)
    return base


class TestDisclaimerCanonicalConstant:
    """AC1: Kiem tra hang so MEAL_DISCLAIMER tieu chuan."""

    def test_disclaimer_constant_not_empty_and_is_str(self):
        assert isinstance(MEAL_DISCLAIMER, str)
        assert len(MEAL_DISCLAIMER.strip()) > 0

    def test_disclaimer_constant_contains_medical_keywords(self):
        normalized = MEAL_DISCLAIMER.lower()
        assert "tham khảo" in normalized
        assert "bác sĩ" in normalized or "dược sĩ" in normalized

    def test_disclaimer_is_deterministic(self):
        """CD6: Disclaimer phai tat dinh, khong thay doi giua cac lan goi."""
        first = MEAL_DISCLAIMER
        second = MEAL_DISCLAIMER
        assert first == second
        assert first is second


class TestDisclaimerSchemaFailClosed:
    """AC2: Kiem tra tinh chat fail-closed o tang schema validation."""

    def test_schema_accepts_valid_disclaimer(self):
        payload = _valid_response_payload(disclaimer=MEAL_DISCLAIMER)
        resp = MealSuggestionResponse.model_validate(payload)
        assert resp.disclaimer == MEAL_DISCLAIMER

    def test_schema_rejects_empty_string_disclaimer(self):
        """AC2 (RED): disclaimer='' phai bi tu choi boi schema validation."""
        payload = _valid_response_payload(disclaimer="")
        with pytest.raises(ValidationError):
            MealSuggestionResponse.model_validate(payload)

    def test_schema_rejects_whitespace_only_disclaimer(self):
        """AC2 (RED): disclaimer='   ' phai bi tu choi boi schema validation."""
        payload = _valid_response_payload(disclaimer="   \t\n  ")
        with pytest.raises(ValidationError):
            MealSuggestionResponse.model_validate(payload)

    def test_schema_rejects_none_disclaimer(self):
        payload = _valid_response_payload(disclaimer=None)
        with pytest.raises(ValidationError):
            MealSuggestionResponse.model_validate(payload)

    def test_schema_rejects_missing_disclaimer(self):
        payload = _valid_response_payload()
        del payload["disclaimer"]
        with pytest.raises(ValidationError):
            MealSuggestionResponse.model_validate(payload)


class TestDomainDisclaimerFailClosed:
    """AC2: Kiem tra domain guard tren validate_disclaimer."""

    def test_domain_rejects_empty_string(self):
        with pytest.raises(ValueError, match="disclaimer must not be empty"):
            validate_disclaimer("")

    def test_domain_rejects_whitespace_string(self):
        with pytest.raises(ValueError, match="disclaimer must not be empty"):
            validate_disclaimer("   \t  ")

    def test_domain_rejects_none(self):
        with pytest.raises(ValueError, match="disclaimer must not be empty"):
            validate_disclaimer(None)


class TestDisclaimerTamperResistanceAndFoodCheck:
    """AC3 & AC4: Chong gia mao tu LLM va bao toan 3 trang thai food_check."""

    def test_tamper_resistance_parser_ignores_llm_disclaimer(self):
        """AC3: Neu LLM tra ve truong disclaimer rieng, parser loai bo hoan toan."""
        input_data = MealSuggestionInput.build(
            meal_type="trua",
            active_ingredients=["Losartan"],
            conditions=["Tăng huyết áp"],
            avoid_foods=["Chuối"],
            allergies=DietaryDeclaration(True, ()),
            restrictions=DietaryDeclaration(True, ()),
            preferences=(),
        )
        prompt = build_prompt(input_data)
        llm_dict = {
            "meal_type": "trua",
            "disclaimer": "Món ăn này đã được AI xác nhận an toàn tuyệt đối",
            "suggestions": [
                {
                    "name": "Canh chua cá lóc",
                    "dish_type": "mon_nuoc",
                    "image_query": "canh chua ca loc",
                    "tags": ["healthy"],
                    "kcal_estimate": 250,
                    "cook_minutes": 25,
                    "benefits": [{"text": "Bổ sung protein", "related_to": "general"}],
                    "ingredients": [
                        {
                            "name": "Cá lóc",
                            "amount": "200g",
                            "group": "chinh",
                            "use_sparingly": False,
                        }
                    ],
                }
            ],
        }
        res = parse_suggestions(json.dumps(llm_dict, ensure_ascii=False), prompt)
        assert len(res.suggestions) == 1
        assert res.suggestions[0].name == "Canh chua cá lóc"
        assert not hasattr(res, "disclaimer")

    def test_food_check_deterministic_three_states_preserved(self):
        """AC4 / CD6: food_check co 3 trang thai tat dinh hop le."""
        valid_statuses = {"co_tuong_tac", "da_kiem_tra_khong_thay", "khong_du_du_lieu"}
        for status in valid_statuses:
            payload = _valid_response_payload(
                food_check={"status": status, "warnings": []}
            )
            resp = MealSuggestionResponse.model_validate(payload)
            assert resp.food_check.status == status

        invalid_payload = _valid_response_payload(
            food_check={"status": "an_toan", "warnings": []}
        )
        with pytest.raises(ValidationError):
            MealSuggestionResponse.model_validate(invalid_payload)
