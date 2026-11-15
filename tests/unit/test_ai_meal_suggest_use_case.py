"""Use case suggest_meals (task 4.26: AC2, AC4, AC10, AC13, AC14, AC17)."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from drugtime.modules.access.domain.rules import Action, Scope
from drugtime.modules.ai_meal.adapters.outbound.other_modules import (
    InteractionFoodCheck,
    MedicationConditions,
)
from drugtime.modules.ai_meal.adapters.outbound.sql_meal_suggestions import SqlMealSuggestions
from drugtime.modules.ai_meal.application import suggest_meals as uc
from drugtime.modules.ai_meal.application.ports import FoodCheck, FoodWarningView
from drugtime.modules.ai_meal.domain.errors import (
    LlmDisabled,
    LlmInvalidOutput,
    MealInputIncomplete,
)
from drugtime.modules.ai_meal.domain.model import DietaryDeclaration
from drugtime.modules.interaction.domain.evaluator import CheckResult
from drugtime.modules.interaction.domain.food_evaluator import (
    FoodMedicationResult,
    FoodReport,
    FoodWarning,
    IngredientRef,
    MedicationSummary,
)
from drugtime.shared.errors import Forbidden

PATIENT = uuid4()
T0 = datetime(2026, 11, 16, 4, 30, tzinfo=UTC)
WARNING = FoodWarningView(81, 930, 620, "Losartan", "Thực phẩm giàu kali (chuối, cam)", 2,
                          "Tăng kali máu", "Dược thư")
CHECK = FoodCheck("co_tuong_tac", (WARNING,), ("Losartan",), ("Cozaar 50mg",))

GOOD = json.dumps({
    "meal_type": "trua",
    "suggestions": [
        {"name": "Sinh tố chuối", "tags": [], "kcal_estimate": 300, "cook_minutes": 5,
         "benefits": [{"text": "Mát", "related_to": "general"}],
         "ingredients": [{"name": "Chuối", "amount": "1 quả", "group": "chinh",
                          "use_sparingly": False}]},
        {"name": "Cơm gà luộc", "tags": ["Ít muối"], "kcal_estimate": 500, "cook_minutes": 30,
         "benefits": [{"text": "Ít muối, tốt cho huyết áp", "related_to": "condition:1"}],
         "ingredients": [{"name": "Gà", "amount": "120 g", "group": "chinh",
                          "use_sparingly": False}]},
    ],
}, ensure_ascii=False)


class Calls(list):
    pass


class FakeFood:
    def __init__(self, calls, check=CHECK):
        self.calls, self.check = calls, check

    def read(self, uow, patient_id):
        self.calls.append("food")
        return self.check


class FakeConditions:
    def __init__(self, calls):
        self.calls = calls

    def names(self, uow, patient_id):
        self.calls.append("conditions")
        return ["Tăng huyết áp"]


class FakeSuggester:
    def __init__(self, calls, raw=GOOD):
        self.calls, self.raw, self.prompts = calls, raw, []

    def suggest(self, prompt):
        self.calls.append("llm")
        self.prompts.append(prompt)
        return self.raw


class FakeStore:
    def __init__(self, calls, fail=False):
        self.calls, self.fail, self.rows = calls, fail, []

    def insert(self, uow, user_id, content):
        self.calls.append("store")
        if self.fail:
            raise RuntimeError("db down")
        self.rows.append((user_id, content))
        return 3051, T0


def _request(**overrides):
    values = dict(
        meal_type="trua",
        allergies=DietaryDeclaration(False, ("Tôm",)),
        dietary_restrictions=DietaryDeclaration(True, ()),
        preferences=("Ít cay",),
    )
    values.update(overrides)
    return uc.MealRequest(**values)


def run(calls, *, request=None, suggester="default", store=None, authorize=None):
    def default_authorize(*args, **kwargs):
        calls.append(("authorize", kwargs))

    sug = FakeSuggester(calls) if suggester == "default" else suggester
    store = store or FakeStore(calls)
    with patch.object(uc.access, "authorize", side_effect=authorize or default_authorize):
        outcome = uc.suggest_meals(
            object(),
            caller_id=PATIENT,
            caller_is_admin=False,
            patient_id=PATIENT,
            request=request or _request(),
            suggester=sug,
            food=FakeFood(calls),
            conditions=FakeConditions(calls),
            store=store,
        )
    return outcome, sug, store


def test_order_pep_first_then_reads_llm_store():
    calls = Calls()
    outcome, _, store = run(calls)
    assert calls[0][0] == "authorize"
    kwargs = calls[0][1]
    assert (kwargs["scope"], kwargs["action"], kwargs["audit_self"]) == (
        Scope.MEAL, Action.WRITE, True)
    assert calls[1:] == ["food", "conditions", "llm", "store"]
    assert outcome.suggestion_id == 3051 and outcome.created_at == T0
    assert outcome.food is CHECK


def test_filters_avoid_food_from_rules_and_stores_parsed_only__AC6d_AC13():
    calls = Calls()
    outcome, _, store = run(calls)
    assert [m.name for m in outcome.result.suggestions] == ["Cơm gà luộc"]
    (user_id, content), = store.rows
    assert user_id == PATIENT
    assert content["prompt_version"] == "meal-v1" and content["meal_type"] == "trua"
    assert [m["name"] for m in content["suggestions"]] == ["Cơm gà luộc"]
    assert "Tôm" not in json.dumps(content, ensure_ascii=False)  # không lưu dị ứng thô


def test_input_built_from_food_report_and_conditions__AC2():
    calls = Calls()
    _, sug, _ = run(calls)
    prompt = sug.prompts[0]
    for expected in ("Losartan", "Tăng huyết áp", "chuối, cam", "Tôm", "Ít cay"):
        assert expected in prompt.user
    for leaked in (str(PATIENT), "Cozaar"):
        assert leaked not in prompt.user + prompt.system


def test_forbidden_before_any_read_or_llm__AC14():
    calls = Calls()

    def deny(*args, **kwargs):
        raise Forbidden("khong_co_quyen")

    with pytest.raises(Forbidden):
        run(calls, authorize=deny)
    assert calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"allergies": None},
        {"dietary_restrictions": None},
        {"allergies": DietaryDeclaration(False, ())},
        {"dietary_restrictions": DietaryDeclaration(True, ("Chay",))},
        {"meal_type": "khuya"},
    ],
)
def test_incomplete_input_never_calls_provider__AC4(overrides):
    calls = Calls()
    with pytest.raises(MealInputIncomplete):
        run(calls, request=_request(**overrides))
    assert "llm" not in calls and "store" not in calls


def test_disabled_or_no_key_never_calls_provider__AC10():
    calls = Calls()
    with pytest.raises(LlmDisabled):
        run(calls, suggester=None)
    assert [c for c in calls if not isinstance(c, tuple)] == []


def test_invalid_output_not_stored__AC12():
    calls = Calls()
    with pytest.raises(LlmInvalidOutput):
        run(calls, suggester=FakeSuggester(calls, raw="không phải JSON"))
    assert "store" not in calls


def test_store_failure_propagates__AC17():
    calls = Calls()
    with pytest.raises(RuntimeError):
        run(calls, store=FakeStore(calls, fail=True))



# --- Adapter sang module khác (P8, P9) ---------------------------------------------------------


def _food_report():
    los, met = IngredientRef(620, "Losartan"), IngredientRef(630, "Metformin")
    w_kali = FoodWarning(81, 930, los, "Chuối", 2, "Kali", "DT")
    w_ruou = FoodWarning(90, 950, met, "Rượu", 3, "Nhiễm toan", "DT")
    med = lambda um, name, ing, ws: FoodMedicationResult(  # noqa: E731
        um, MedicationSummary(um, name, None, None, None), True, CheckResult.FOUND, ing, ws)
    return FoodReport(
        status=CheckResult.FOUND,
        medications=(
            med(1, "Cozaar", (los,), (w_kali,)),
            med(2, "Losartan Stada", (los,), (w_kali,)),  # cùng hoạt chất → trùng quy tắc
            med(3, "Glucophage", (met,), (w_ruou,)),
        ),
    )


def test_food_check_adapter_flattens_sorts_dedupes__AC13():
    with patch(
        "drugtime.modules.ai_meal.adapters.outbound.other_modules.interaction.patient_food_report",
        return_value=_food_report(),
    ) as read:
        check = InteractionFoodCheck().read("uow", PATIENT)
    read.assert_called_once_with("uow", PATIENT)
    assert check.status == "co_tuong_tac"
    assert [(w.food_to_avoid, w.severity_level) for w in check.warnings] == [
        ("Rượu", 3), ("Chuối", 2)]
    assert check.ingredient_names == ("Losartan", "Metformin")
    assert check.medication_names == ("Cozaar", "Glucophage", "Losartan Stada")


def test_condition_adapter_delegates_to_medication_api():
    with patch(
        "drugtime.modules.ai_meal.adapters.outbound.other_modules.medication."
        "patient_condition_names",
        return_value=["Tăng huyết áp"],
    ) as names:
        assert MedicationConditions().names("uow", PATIENT) == ["Tăng huyết áp"]
    names.assert_called_once_with("uow", PATIENT)


def test_patient_condition_names_sorted_from_profile__P8():
    from drugtime.modules.medication import api as medication

    links = [MagicMock(condition_id=7), MagicMock(condition_id=3), MagicMock(condition_id=7)]
    with patch.object(medication, "SqlUserConditions") as sql, patch.object(
        medication, "ConditionCatalogAdapter"
    ) as cat:
        sql.return_value.list.return_value = links
        cat.return_value.names.return_value = {3: "Tăng huyết áp", 7: "Đái tháo đường"}
        assert medication.patient_condition_names("uow", PATIENT) == [
            "Tăng huyết áp", "Đái tháo đường"]  # sắp theo chuỗi
        cat.return_value.names.assert_called_once_with("uow", [3, 7])
        sql.return_value.list.return_value = []
        assert medication.patient_condition_names("uow", PATIENT) == []


def test_sql_store_inserts_json_and_returns_id__P9():
    uow = MagicMock()
    uow.connection.execute.return_value.one.return_value = MagicMock(id=3051, created_at=T0)
    assert SqlMealSuggestions().insert(uow, PATIENT, {"meal_type": "trua", "x": "Gà"}) == (3051, T0)
    sql, params = uow.connection.execute.call_args.args
    assert "INSERT INTO meal_suggestions" in str(sql) and "false" in str(sql)
    assert params == {"u": PATIENT, "c": '{"meal_type": "trua", "x": "Gà"}'}
