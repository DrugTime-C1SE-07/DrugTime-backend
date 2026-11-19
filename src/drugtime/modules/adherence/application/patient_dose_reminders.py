from dataclasses import dataclass
from math import ceil

from drugtime.modules.adherence.domain.patient_dose_reminder import (
    COOLDOWN,
    ReminderCommand,
    ReminderRecord,
    validate_occurrence,
)
from drugtime.shared.errors import Conflict, Forbidden, NotFound, TooManyRequests


def authorize_reminder(uow, user_id, is_admin, patient_id, access):
    access.authorize_history(uow, user_id, is_admin, patient_id)


def send_reminder(
    uow,
    *,
    caller_id,
    caller_is_admin,
    patient_id,
    cmd: ReminderCommand,
    access,
    schedules,
    doses,
    store,
) -> tuple[ReminderRecord, bool]:
    authorize_reminder(uow, caller_id, caller_is_admin, patient_id, access)
    if caller_id == patient_id:
        raise Forbidden("khong_co_quyen")
    now = store.lock(uow, caller_id, patient_id, cmd)
    previous = store.by_uuid(uow, caller_id, cmd.client_uuid)
    if previous is not None:
        if not previous.matches(patient_id, cmd):
            raise Conflict("client_uuid_conflict")
        return previous, False
    context = schedules.reminder_context(uow, cmd.schedule_id, lock=True)
    validate_occurrence(context, patient_id, cmd.scheduled_at, now, sending=True)
    if doses.confirmed(uow, cmd.schedule_id, cmd.scheduled_at, lock=True):
        raise Conflict("dose_already_confirmed")
    last = store.latest(uow, caller_id, patient_id, cmd.schedule_id, cmd.scheduled_at)
    if last is not None and last.next_allowed_at > now:
        raise TooManyRequests(
            "reminder_cooldown", ceil((last.next_allowed_at - now).total_seconds())
        )
    return store.create(uow, caller_id, patient_id, cmd, now, now + COOLDOWN), True


def reminder_state(
    uow,
    *,
    caller_id,
    caller_is_admin,
    patient_id,
    schedule_id,
    scheduled_at,
    access,
    schedules,
    store,
):
    authorize_reminder(uow, caller_id, caller_is_admin, patient_id, access)
    if caller_id == patient_id:
        raise Forbidden("khong_co_quyen")
    context = schedules.reminder_context(uow, schedule_id)
    validate_occurrence(context, patient_id, scheduled_at, store.now(uow), sending=False)
    return store.latest(uow, caller_id, patient_id, schedule_id, scheduled_at)


@dataclass(frozen=True)
class ReceivedReminder:
    record: ReminderRecord
    medication_name: str
    sender_name: str | None


def _received_access(uow, user_id, is_admin, sender_id, access):
    authorize_reminder(uow, user_id, is_admin, user_id, access)
    authorize_reminder(uow, sender_id, False, user_id, access)


def _received(uow, record, schedules, names):
    medication_name = schedules.alert_context(uow, record.schedule_id, record.patient_id)
    if medication_name is None:
        raise NotFound("dose_reminder_not_found")
    name = names.get_patient_name(uow, record.sender_user_id)
    return ReceivedReminder(record, medication_name, (name.strip() or None) if name else None)


def received_detail(
    uow, *, user_id, caller_is_admin, reminder_id, access, schedules, names, store, is_read=None
):
    # Ownership routing metadata only; health fields are loaded after both PEP checks.
    metadata = store.received_metadata(uow, user_id, reminder_id)
    if not metadata:
        raise NotFound("dose_reminder_not_found")
    _received_access(uow, user_id, caller_is_admin, metadata[0][1], access)
    record = store.received_record(uow, user_id, reminder_id, is_read)
    if record is None:
        raise NotFound("dose_reminder_not_found")
    return _received(uow, record, schedules, names)


def received_list(
    uow, *, user_id, caller_is_admin, is_read, limit, offset, access, schedules, names, store
):
    authorize_reminder(uow, user_id, caller_is_admin, user_id, access)
    allowed = []
    for reminder_id, sender in store.received_metadata(uow, user_id):
        try:
            authorize_reminder(uow, sender, False, user_id, access)
        except Forbidden:
            continue
        allowed.append(reminder_id)
    records = store.received_records(uow, user_id, allowed)
    unread = sum(not r.is_read for r in records)
    matched = [r for r in records if is_read is None or r.is_read == is_read]
    return (
        [_received(uow, r, schedules, names) for r in matched[offset : offset + limit]],
        len(matched),
        unread,
    )
