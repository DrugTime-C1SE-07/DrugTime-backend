from datetime import time
from decimal import Decimal
from uuid import uuid4

import pytest

from drugtime.modules.medication.domain.user_medication import (
    ALL_WEEK,
    DosingMode,
    IntakeTiming,
    MedicationChanges,
    MedicationState,
    NewMedication,
    plan_update,
    validate_new,
)
from drugtime.shared.errors import DomainError

S, A = DosingMode.SCHEDULED, DosingMode.AS_NEEDED


def new(**kw):
    base = dict(
        client_uuid=uuid4(),
        medication_id=1,
        quantity_per_dose=Decimal("1"),
        dosing_mode=S,
        intake_times=(time(20), time(8)),
    )
    return NewMedication(**{**base, **kw})


def changes(**kw):
    return MedicationChanges(sent=frozenset(kw), **kw)


def state(mode=S, stopped=False, days=(1, 3, 5)):
    return MedicationState(mode, stopped, days if mode is S and not stopped else None)


def rule_error(code="medication_rule_violation"):
    return pytest.raises(DomainError, match=f"^{code}$")


# --- validate_new -----------------------------------------------------------


def test_validate_new_scheduled_sorts_times_and_defaults_whole_week():
    cmd = validate_new(new())
    assert cmd.intake_times == (time(8), time(20))
    assert cmd.days_of_week == ALL_WEEK
    assert cmd.doses_per_day == 2
    assert validate_new(new(days_of_week=(5, 1))).days_of_week == (1, 5)


def test_validate_new_as_needed_uses_max_doses():
    cmd = validate_new(new(dosing_mode=A, intake_times=None, max_doses_per_day=3))
    assert cmd.doses_per_day == 3


@pytest.mark.parametrize(
    "kw",
    [
        dict(intake_times=None),  # scheduled thiếu giờ
        dict(max_doses_per_day=2),  # scheduled kèm số lần tối đa
        dict(dosing_mode=A, intake_times=None),  # as_needed thiếu số lần tối đa
        dict(dosing_mode=A, max_doses_per_day=2),  # as_needed kèm giờ
        dict(dosing_mode=A, intake_times=None, max_doses_per_day=2, days_of_week=(1,)),
    ],
)
def test_validate_new_rejects_fields_of_other_mode(kw):
    with rule_error():
        validate_new(new(**kw))


# --- plan_update ------------------------------------------------------------


def test_plan_update_dose_keeps_schedules():
    p = plan_update(state(), changes(quantity_per_dose=Decimal("2")))
    assert p.fields == {"quantity_per_dose": Decimal("2")}
    assert not p.close_open_schedules and not p.new_intake_times and not p.stop


def test_plan_update_timing_and_stock_including_null():
    p = plan_update(state(), changes(intake_timing=IntakeTiming.AFTER_MEAL, stock_quantity=None))
    assert p.fields == {"intake_timing": IntakeTiming.AFTER_MEAL, "stock_quantity": None}
    assert not p.close_open_schedules


def test_plan_update_times_closes_old_and_keeps_days_of_week():
    p = plan_update(state(days=(1, 3, 5)), changes(intake_times=(time(19), time(7), time(12))))
    assert p.close_open_schedules
    assert p.new_intake_times == (time(7), time(12), time(19))
    assert p.new_days_of_week == (1, 3, 5)
    assert p.fields == {"doses_per_day": 3}


def test_plan_update_scheduled_to_as_needed():
    p = plan_update(state(), changes(dosing_mode=A, max_doses_per_day=2))
    assert p.fields == {"dosing_mode": A, "doses_per_day": 2}
    assert p.close_open_schedules and not p.new_intake_times


def test_plan_update_as_needed_to_scheduled_uses_whole_week():
    p = plan_update(state(A), changes(dosing_mode=S, intake_times=(time(8),)))
    assert p.fields == {"dosing_mode": S, "doses_per_day": 1}
    assert p.new_intake_times == (time(8),) and p.new_days_of_week == ALL_WEEK


def test_plan_update_max_doses_on_as_needed():
    p = plan_update(state(A), changes(max_doses_per_day=4))
    assert p.fields == {"doses_per_day": 4} and not p.close_open_schedules


def test_plan_update_same_mode_is_not_a_switch():
    assert plan_update(state(), changes(dosing_mode=S)).is_noop


def test_plan_update_stop_and_repeat_stop():
    p = plan_update(state(), changes(stopped=True))
    assert p.stop and p.close_open_schedules and p.fields == {}
    assert plan_update(state(stopped=True), changes(stopped=True)).is_noop


@pytest.mark.parametrize(
    "st, ch",
    [
        (state(), changes()),  # body rỗng
        (state(), changes(stopped=True, quantity_per_dose=Decimal("1"))),  # stopped kèm field khác
        (state(A), changes(intake_times=(time(8),))),  # giờ khi đang as_needed
        (state(), changes(max_doses_per_day=2)),  # số lần tối đa khi đang scheduled
        (state(), changes(dosing_mode=A)),  # chuyển chế độ thiếu field bắt buộc
        (state(A), changes(dosing_mode=S)),
        (state(), changes(dosing_mode=A, intake_times=(time(8),), max_doses_per_day=2)),
        (state(A), changes(dosing_mode=S, intake_times=(time(8),), max_doses_per_day=2)),
    ],
)
def test_plan_update_rule_violations(st, ch):
    with rule_error():
        plan_update(st, ch)


def test_plan_update_stopped_medication_rejects_changes():
    with rule_error("medication_stopped"):
        plan_update(state(stopped=True), changes(quantity_per_dose=Decimal("2")))
