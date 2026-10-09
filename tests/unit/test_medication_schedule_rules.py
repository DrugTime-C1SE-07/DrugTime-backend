from datetime import UTC, datetime, time, timedelta

import pytest

from drugtime.modules.medication.domain.schedule_changes import (
    MAX_SCHEDULES,
    ClosedSchedule,
    NewSchedule,
    ScheduleWrite,
    close_all,
    close_at,
    pick_reactivation,
    plan_add,
    plan_edit,
    plan_reactivation,
    plan_remove,
    replace_all,
    start_at,
)
from drugtime.modules.medication.domain.user_medication import (
    ALL_WEEK,
    DosingMode,
    MedicationState,
    PendingClosed,
    ScheduleView,
)
from drugtime.shared.errors import DomainError, NotFound

T = datetime(2026, 10, 9, 0, 50, tzinfo=UTC)  # 07:50 giờ Việt Nam
PAST = T - timedelta(days=8)
S1 = ScheduleView(1, time(8), (1, 3, 5), True, PAST)
S2 = ScheduleView(2, time(20), (1, 3, 5), True, PAST)
EARLY = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)  # liều 08:00 hôm nay, đã xác nhận sớm


def state(*schedules, mode=DosingMode.SCHEDULED, stopped=False, pending=()):
    days = schedules[0].days_of_week if schedules else None
    return MedicationState(
        mode, stopped, days, open_schedules=tuple(schedules), pending_closed=tuple(pending)
    )


def error(code):
    return pytest.raises(DomainError, match=f"^{code}$")


# --- close_at / start_at ----------------------------------------------------


def test_close_at_without_early_dose_is_T():
    assert close_at(S1, T, None) == T


def test_close_at_after_early_dose_is_one_second_later():
    assert close_at(S1, T, EARLY) == EARLY + timedelta(seconds=1)


def test_close_at_never_before_effective_from():
    future = ScheduleView(9, time(8), ALL_WEEK, True, T + timedelta(minutes=10))
    assert close_at(future, T, None) == future.effective_from


def test_start_at_is_latest_of_T_and_replaced_ends():
    later = T + timedelta(minutes=10)
    assert start_at(T, (), (), time(8)) == T
    assert start_at(T, (T, later), (), time(9)) == later


def test_start_at_waits_for_pending_closed_same_time_only():
    pending = (PendingClosed(time(8), EARLY + timedelta(seconds=1)),)
    assert start_at(T, (), pending, time(8)) == EARLY + timedelta(seconds=1)
    assert start_at(T, (), pending, time(9)) == T


# --- plan_add ---------------------------------------------------------------


def test_add_uses_medication_days_and_default_reminder():
    w = plan_add(state(S1, S2), T, time(12), True)
    assert w == ScheduleWrite(insert=(NewSchedule(time(12), (1, 3, 5), True, T),), doses_per_day=3)
    assert plan_add(state(S1), T, time(12), False).insert[0].reminder_enabled is False


def test_add_waits_for_pending_closed_same_time():
    pending = (PendingClosed(time(8), EARLY + timedelta(seconds=1)),)
    w = plan_add(state(S2, pending=pending), T, time(8), True)
    assert w.insert[0].effective_from == EARLY + timedelta(seconds=1)


def test_add_rejects_stopped_as_needed_conflict_and_limit_in_order():
    with error("medication_stopped"):
        plan_add(state(S1, stopped=True), T, time(8), True)  # dừng đứng trước trùng giờ
    with error("medication_rule_violation"):
        plan_add(state(mode=DosingMode.AS_NEEDED), T, time(8), True)
    with error("schedule_time_conflict"):
        plan_add(state(S1, S2), T, time(8), True)
    full = [ScheduleView(i, time(i), ALL_WEEK, True, PAST) for i in range(1, MAX_SCHEDULES + 1)]
    with error("schedule_time_conflict"):
        plan_add(state(*full), T, time(1), True)  # trùng giờ đứng trước đủ số lịch
    with error("schedule_limit_reached"):
        plan_add(state(*full), T, time(23), True)


# --- plan_edit --------------------------------------------------------------


def test_edit_time_creates_replacement_keeping_other_fields():
    w = plan_edit(state(S1, S2), T, 1, {}, intake_time=time(7))
    assert w.close == ((1, T),)
    assert w.insert == (NewSchedule(time(7), (1, 3, 5), True, T),)
    assert w.doses_per_day is None


def test_edit_reminder_creates_replacement_same_time():
    w = plan_edit(state(S1, S2), T, 1, {}, reminder_enabled=False)
    assert w.close == ((1, T),)
    assert w.insert == (NewSchedule(time(8), (1, 3, 5), False, T),)


@pytest.mark.parametrize(
    "kw",
    [
        {"intake_time": time(8)},
        {"reminder_enabled": True},
        {},
        {"intake_time": time(8), "reminder_enabled": True},
    ],
)
def test_edit_same_values_is_noop(kw):
    assert plan_edit(state(S1, S2), T, 1, {}, **kw).is_noop


def test_edit_conflict_with_other_open_schedule():
    with error("schedule_time_conflict"):
        plan_edit(state(S1, S2), T, 1, {}, intake_time=time(20))
    # đổi nhắc của chính lịch đó không phải trùng giờ
    assert not plan_edit(
        state(S1, S2), T, 1, {}, intake_time=time(8), reminder_enabled=False
    ).is_noop


def test_edit_or_remove_unknown_or_closed_schedule_not_found():
    for call in (
        lambda: plan_edit(state(S1, S2), T, 99, {}, intake_time=time(9)),
        lambda: plan_remove(state(S1, S2), T, 99, {}),
        lambda: plan_edit(state(mode=DosingMode.AS_NEEDED), T, 1, {}, intake_time=time(9)),
    ):
        with pytest.raises(NotFound, match="^medication_schedule_not_found$"):
            call()


def test_edit_and_remove_on_stopped_medication():
    with error("medication_stopped"):
        plan_edit(state(stopped=True), T, 1, {}, intake_time=time(9))
    with error("medication_stopped"):
        plan_remove(state(stopped=True), T, 1, {})


def test_edit_after_early_dose_replacement_starts_after_dose__AC20():
    w = plan_edit(state(S1, S2), T, 1, {1: EARLY}, reminder_enabled=False)
    end = EARLY + timedelta(seconds=1)
    assert w.close == ((1, end),)
    assert w.insert[0].effective_from == end


# --- plan_remove ------------------------------------------------------------


def test_remove_decrements_and_last_schedule_rejected():
    w = plan_remove(state(S1, S2), T, 2, {})
    assert w == ScheduleWrite(close=((2, T),), doses_per_day=1)
    with error("last_schedule_not_removable"):
        plan_remove(state(S1), T, 1, {})


def test_remove_after_early_dose_keeps_dose_inside__AC21():
    assert plan_remove(state(S1, S2), T, 1, {1: EARLY}).close == (
        (1, EARLY + timedelta(seconds=1)),
    )


# --- replace_all ------------------------------------------------------------


def test_replace_all_starts_every_new_schedule_at_latest_end():
    w = replace_all(state(S1, S2), T, {1: EARLY}, (time(8), time(20)), (1, 5), (False, True))
    end = EARLY + timedelta(seconds=1)
    assert w.close == ((1, end), (2, T))
    assert w.insert == (
        NewSchedule(time(8), (1, 5), False, end),
        NewSchedule(time(20), (1, 5), True, end),
    )


def test_replace_all_without_early_dose_starts_at_T():
    w = replace_all(state(S1, S2), T, {}, (time(9),), ALL_WEEK, (True,))
    assert w.close == ((1, T), (2, T))
    assert w.insert == (NewSchedule(time(9), ALL_WEEK, True, T),)


# --- vòng 3–4: close_all, pick_reactivation, plan_reactivation (R1, R3) ---------------------------

ONE = timedelta(seconds=1)


def closed(id_, h, eff, end, rem=True, minute=0):
    return ClosedSchedule(id_, time(h, minute), (1, 3, 5), rem, eff, end)


def test_close_all_without_early_dose_closes_at_T():
    assert close_all(state(S1, S2), T, {}) == ((1, T), (2, T))


def test_close_all_after_early_dose_keeps_dose_inside__AC24():
    assert close_all(state(S1, S2), T, {1: EARLY}) == ((1, EARLY + ONE), (2, T))


def test_pick_reactivation_keeps_siblings_of_one_replacement__R3():
    # Seed 43 của review: 07:00 và 22:00 cùng tạo bởi một lần đổi giờ sau liều sớm, cùng bắt
    # đầu ở tương lai, cùng đóng lúc ngừng (ended_at = effective_from). Cả hai mang dấu ngừng.
    end = EARLY + ONE
    cands = [closed(3, 7, end, end), closed(4, 22, end, end)]
    assert [c.intake_time for c in pick_reactivation(cands)] == [time(7), time(22)]


def test_pick_reactivation_keeps_reminder_and_days():
    cands = [closed(1, 8, PAST, EARLY + ONE, rem=False), closed(2, 20, PAST, T)]
    picked = pick_reactivation(cands)
    assert [(c.id, c.reminder_enabled, c.days_of_week) for c in picked] == [
        (1, False, (1, 3, 5)),
        (2, True, (1, 3, 5)),
    ]


def test_pick_reactivation_one_per_time_highest_id():
    cands = [closed(4, 8, PAST, T), closed(1, 8, PAST, T)]
    assert [c.id for c in pick_reactivation(cands)] == [4]


def test_pick_reactivation_empty():
    assert pick_reactivation([]) == ()


def test_plan_reactivation_waits_for_pending_same_time__AC25():
    later = T + timedelta(minutes=5)
    end = EARLY + ONE
    st = MedicationState(
        DosingMode.SCHEDULED, True, None, pending_closed=(PendingClosed(time(8), end),)
    )
    w = plan_reactivation(st, later, [closed(1, 8, PAST, end), closed(2, 20, PAST, T)])
    assert w.insert == (
        NewSchedule(time(8), (1, 3, 5), True, end),
        NewSchedule(time(20), (1, 3, 5), True, later),
    )
