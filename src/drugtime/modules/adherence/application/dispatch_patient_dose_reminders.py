from hashlib import sha256

from drugtime.modules.adherence.application.patient_dose_reminders import authorize_reminder
from drugtime.modules.adherence.domain.patient_dose_reminder import (
    ReminderPush,
    validate_occurrence,
)
from drugtime.shared.errors import Conflict, DomainError, Forbidden


def _validate(uow_factory, record, access, schedules, doses, store):
    # Audit must commit before transport, including when a job is retried.
    with uow_factory() as uow:
        authorize_reminder(uow, record.sender_user_id, False, record.patient_id, access)
        context = schedules.reminder_context(uow, record.schedule_id)
        validate_occurrence(
            context, record.patient_id, record.scheduled_at, store.now(uow), sending=True
        )
        if doses.confirmed(uow, record.schedule_id, record.scheduled_at):
            raise Conflict("dose_already_confirmed")


def dispatch_reminders(
    uow_factory, *, notifier, access, schedules, doses, tokens, store, limit=100
):
    processed = 0
    for _ in range(limit):
        with uow_factory() as uow:
            claim = store.claim(uow)
        if claim is None:
            break
        with uow_factory() as uow:
            job = store.leased(uow, *claim)
            if job is None:
                continue
            record, attempts, hashes = job
            try:
                _validate(uow_factory, record, access, schedules, doses, store)
                targets = tokens.android_tokens(uow, [record.patient_id])
                remaining = [
                    (token, sha256(token.encode()).hexdigest())
                    for _, token in targets
                    if sha256(token.encode()).hexdigest() not in hashes
                ]
                if not remaining:
                    store.finish(
                        uow,
                        record,
                        status="dispatched" if hashes else "accepted",
                        state="done",
                        attempts=attempts,
                        hashes=hashes,
                        error=None if hashes else "no_targets",
                    )
                    processed += 1
                    continue
                failed = False
                for token, digest in remaining:
                    _validate(uow_factory, record, access, schedules, doses, store)
                    result = notifier.send_reminder(ReminderPush(record.id, token))
                    if result.accepted:
                        hashes.add(digest)
                    elif result.unregistered:
                        tokens.remove(uow, [token])
                    else:
                        failed = True
                attempts += 1
                retry = failed and attempts < 3
                status = (
                    "dispatched" if hashes else ("accepted" if retry or not failed else "failed")
                )
                store.finish(
                    uow,
                    record,
                    status=status,
                    state="pending" if retry else ("dead" if failed else "done"),
                    attempts=attempts,
                    hashes=hashes,
                    error="transport_unavailable" if failed else None,
                    delay=(30 if attempts == 1 else 120) if retry else 0,
                )
            except (Forbidden, Conflict, DomainError):
                store.finish(
                    uow,
                    record,
                    status="cancelled",
                    state="done",
                    attempts=attempts,
                    hashes=hashes,
                    error="no_longer_eligible",
                )
        processed += 1
    with uow_factory() as uow:
        store.cleanup(uow)
    return processed
