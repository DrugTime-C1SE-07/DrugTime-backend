from datetime import UTC, datetime, time
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
    ScheduleView,
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


def test_plan_update_unstop_stopped_reactivates():
    p = plan_update(state(stopped=True), changes(stopped=False))
    assert p.reactivate and not p.stop and not p.close_open_schedules and p.fields == {}
    assert not p.is_noop


def test_plan_update_unstop_active_is_noop():
    assert plan_update(state(), changes(stopped=False)).is_noop
    assert plan_update(state(A), changes(stopped=False)).is_noop


@pytest.mark.parametrize("stopped", [True, False])
def test_plan_update_stop_or_unstop_with_other_field_violation(stopped):
    with rule_error():
        plan_update(state(stopped=True), changes(stopped=stopped, stock_quantity=3))


def test_plan_update_stop_does_not_reactivate():
    assert not plan_update(state(), changes(stopped=True)).reactivate


def test_plan_update_stopped_medication_rejects_changes():
    with rule_error("medication_stopped"):
        plan_update(state(stopped=True), changes(quantity_per_dose=Decimal("2")))


# --- task 2.04: days_of_week và giữ trạng thái nhắc -----------------------------------------

_PAST = datetime(2026, 10, 1, tzinfo=UTC)


def state_with(*specs, days=(1, 3, 5)):
    """specs: (giờ, nhắc) của các lịch đang mở."""
    schedules = tuple(
        ScheduleView(i, time(h), days, rem, _PAST) for i, (h, rem) in enumerate(specs, 1)
    )
    return MedicationState(S, False, days, open_schedules=schedules)


def test_plan_update_days_only_recreates_with_same_times_and_reminders():
    p = plan_update(state_with((8, True), (20, False)), changes(days_of_week=(5, 1)))
    assert p.close_open_schedules
    assert p.new_intake_times == (time(8), time(20))
    assert p.new_days_of_week == (1, 5)
    assert p.new_reminders == (True, False)
    assert "doses_per_day" not in p.fields


def test_plan_update_same_days_is_noop():
    assert plan_update(state_with((8, True)), changes(days_of_week=(5, 3, 1))).is_noop


def test_plan_update_days_with_other_field_keeps_schedules_when_same_days():
    p = plan_update(state_with((8, True)), changes(days_of_week=(1, 3, 5), quantity_per_dose=2))
    assert p.fields == {"quantity_per_dose": 2} and not p.close_open_schedules


@pytest.mark.parametrize(
    "st, ch",
    [
        (state(A), changes(days_of_week=(1,))),
        (state(S), changes(dosing_mode=A, max_doses_per_day=2, days_of_week=(1,))),
        (state(S), changes(stopped=True, days_of_week=(1,))),
    ],
)
def test_plan_update_days_with_as_needed_or_stop_violation(st, ch):
    with rule_error():
        plan_update(st, ch)


def test_plan_update_times_keep_reminder_of_existing_times__AC10():
    p = plan_update(
        state_with((8, True), (20, False)), changes(intake_times=(time(22), time(20), time(8)))
    )
    assert p.new_intake_times == (time(8), time(20), time(22))
    assert p.new_reminders == (True, False, True)
    assert p.new_days_of_week == (1, 3, 5)
    assert p.fields["doses_per_day"] == 3


def test_plan_update_times_with_days_uses_sent_days():
    p = plan_update(state_with((8, True)), changes(intake_times=(time(9),), days_of_week=(7, 6)))
    assert p.new_intake_times == (time(9),) and p.new_days_of_week == (6, 7)


def test_switch_to_scheduled_with_days():
    p = plan_update(state(A), changes(dosing_mode=S, intake_times=(time(9),), days_of_week=(2, 4)))
    assert p.new_days_of_week == (2, 4) and p.new_reminders == (True,)
    p = plan_update(state(A), changes(dosing_mode=S, intake_times=(time(9),)))
    assert p.new_days_of_week == ALL_WEEK


def test_switch_to_scheduled_with_only_days_violation():
    with rule_error():
        plan_update(state(A), changes(dosing_mode=S, days_of_week=(1,)))
