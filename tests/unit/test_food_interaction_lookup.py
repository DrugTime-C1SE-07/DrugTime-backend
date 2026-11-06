"""Unit test use case lookup_food_interactions (task 4.05: AC8–AC14b, AC17, AC23)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from drugtime.modules.access.domain.rules import Action, Scope
from drugtime.modules.interaction.application import lookup_food_interactions as uc
from drugtime.modules.interaction.domain.catalog_rules import (
    DrugFoodInteractionContent,
    RuleRecord,
    VersionMeta,
)
from drugtime.modules.interaction.domain.evaluator import CheckResult
from drugtime.shared.errors import Forbidden, NotFound

PATIENT = uuid4()
CALLER = uuid4()
T0 = datetime(2026, 11, 6, tzinfo=UTC)


@dataclass(frozen=True)
class Ref:
    user_medication_id: int
    medication_id: int
    is_active: bool


@dataclass(frozen=True)
class Info:
    id: int
    name: str
    active_ingredient: str | None = None
    strength_text: str | None = None
    dosage_form: str | None = None


class Calls(list):
    pass


class FakeMeds:
    def __init__(self, calls, active=(), one=None):
        self.calls, self._active, self._one = calls, list(active), one

    def active(self, uow, patient_id):
        self.calls.append(("meds.active", patient_id))
        return self._active

    def one(self, uow, patient_id, user_medication_id):
        self.calls.append(("meds.one", patient_id, user_medication_id))
        return self._one


class FakeCatalog:
    def __init__(self, calls, infos):
        self.calls, self.infos = calls, infos

    def get(self, uow, medication_id):
        self.calls.append(("catalog.get", medication_id))
        return self.infos.get(medication_id)


class FakeIngredients:
    def __init__(self, calls, by_med, names):
        self.calls, self.by_med, self._names = calls, by_med, names

    def ids_of_medication(self, uow, medication_id):
        self.calls.append(("ingredients.of", medication_id))
        return self.by_med.get(medication_id, [])

    def names(self, uow, ids):
        self.calls.append(("ingredients.names", tuple(ids)))
        return {i: self._names[i] for i in ids if i in self._names}


class FakeRules:
    def __init__(self, calls, rules):
        self.calls, self.rules = calls, rules

    def active_rules_for_ingredients(self, uow, ids):
        self.calls.append(("rules", tuple(ids)))
        return [r for r in self.rules if r.content.ingredient_id in ids]


def rule(version_id, ingredient, food="Rượu", severity=3):
    return RuleRecord(
        content=DrugFoodInteractionContent(ingredient, food, severity, "r", "s"),
        meta=VersionMeta(version_id, 1, version_id, T0, T0, None, None, None, None),
    )


def run(calls, *, meds, infos, by_med=None, rules=(), user_medication_id=None, authorize=None):
    def default_authorize(*args, **kwargs):
        calls.append(("authorize", kwargs))

    with patch.object(uc.access, "authorize", side_effect=authorize or default_authorize):
        return uc.lookup_food_interactions(
            object(),
            caller_id=CALLER,
            caller_is_admin=False,
            patient_id=PATIENT,
            user_medication_id=user_medication_id,
            medications=meds,
            catalog=FakeCatalog(calls, infos),
            ingredients=FakeIngredients(calls, by_med or {}, {1: "A", 2: "B"}),
            rules=FakeRules(calls, list(rules)),
        )


def test_authorize_called_first_with_audit_self__AC10_AC17():
    calls = Calls()
    meds = FakeMeds(calls, active=[Ref(5, 50, True)])
    report = run(calls, meds=meds, infos={50: Info(50, "M")}, by_med={50: [1]}, rules=[rule(9, 1)])
    name, kwargs = calls[0]
    assert name == "authorize"
    assert kwargs["patient_id"] == PATIENT and kwargs["caller_id"] == CALLER
    assert kwargs["scope"] is Scope.INTERACTIONS and kwargs["action"] is Action.READ
    assert kwargs["audit_self"] is True
    assert report.status is CheckResult.FOUND


def test_forbidden_stops_before_any_read__AC11_AC14():
    calls = Calls()

    def deny(*args, **kwargs):
        raise Forbidden("khong_co_quyen")

    with pytest.raises(Forbidden):
        run(calls, meds=FakeMeds(calls, active=[Ref(5, 50, True)]), infos={}, authorize=deny)
    assert calls == []


def test_unknown_or_foreign_medication_404_after_authorize__AC9():
    calls = Calls()
    with pytest.raises(NotFound) as exc:
        run(calls, meds=FakeMeds(calls, one=None), infos={}, user_medication_id=77)
    assert str(exc.value) == "user_medication_not_found"
    assert [c[0] for c in calls] == ["authorize", "meds.one"]
    assert calls[1] == ("meds.one", PATIENT, 77)


def test_filtered_stopped_medication_returned_inactive__AC8():
    calls = Calls()
    meds = FakeMeds(calls, one=Ref(8, 80, False))
    report = run(
        calls, meds=meds, infos={80: Info(80, "M")}, by_med={80: [2]}, user_medication_id=8
    )
    [m] = report.medications
    assert (m.user_medication_id, m.is_active, m.status) == (8, False, CheckResult.NONE_FOUND)
    assert ("meds.active", PATIENT) not in calls


def test_unfiltered_uses_active_medications_in_order__AC8():
    calls = Calls()
    meds = FakeMeds(calls, active=[Ref(1, 10, True), Ref(2, 20, True)])
    report = run(calls, meds=meds, infos={10: Info(10, "A"), 20: Info(20, "B")}, by_med={10: [1]})
    assert [m.user_medication_id for m in report.medications] == [1, 2]
    assert [m.status for m in report.medications] == [
        CheckResult.NONE_FOUND,
        CheckResult.INSUFFICIENT_DATA,
    ]
    assert report.status is CheckResult.INSUFFICIENT_DATA


def test_rules_loaded_once_for_all_ingredients():
    calls = Calls()
    meds = FakeMeds(calls, active=[Ref(1, 10, True), Ref(2, 20, True)])
    infos = {10: Info(10, "A"), 20: Info(20, "B")}
    run(calls, meds=meds, infos=infos, by_med={10: [2], 20: [1, 2]})
    assert [c for c in calls if c[0] == "rules"] == [("rules", (1, 2))]


def test_deleted_catalog_medication_still_evaluated__AC23():
    """Adapter thật đọc danh mục với include_deleted=True; ở đây kiểm use case không lọc bỏ."""
    calls = Calls()
    meds = FakeMeds(calls, active=[Ref(1, 10, True)])
    report = run(
        calls, meds=meds, infos={10: Info(10, "Đã gỡ")}, by_med={10: [1]}, rules=[rule(3, 1)]
    )
    assert report.medications[0].medication.name == "Đã gỡ"
    assert report.medications[0].status is CheckResult.FOUND


def test_catalog_adapter_reads_deleted_medications__AC23():
    from drugtime.modules.interaction.adapters.outbound.other_modules import CatalogMedications

    with patch(
        "drugtime.modules.interaction.adapters.outbound.other_modules.catalog.get_medication"
    ) as get:
        CatalogMedications().get(object(), 10)
    assert get.call_args.kwargs == {"include_deleted": True}


def test_missing_catalog_row_is_error_not_guess():
    calls = Calls()
    with pytest.raises(LookupError):
        run(calls, meds=FakeMeds(calls, active=[Ref(1, 10, True)]), infos={})


def test_access_log_failure_propagates_no_result__AC14b():
    calls = Calls()

    def log_fails(*args, **kwargs):
        raise RuntimeError("access_logs unavailable")

    with pytest.raises(RuntimeError):
        run(calls, meds=FakeMeds(calls, active=[Ref(1, 10, True)]), infos={}, authorize=log_fails)
    assert calls == []


def test_empty_patient_list_is_insufficient__AC15():
    calls = Calls()
    report = run(calls, meds=FakeMeds(calls, active=[]), infos={})
    assert report.medications == () and report.status is CheckResult.INSUFFICIENT_DATA
    assert ("ingredients.names", ()) not in calls
