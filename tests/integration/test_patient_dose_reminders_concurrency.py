"""Concurrent requests against the real local database."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

pytest_plugins = ["test_patient_dose_reminders_api"]


@pytest.mark.parametrize("same_key", [True, False], ids=["replay", "cooldown"])
def test_simultaneous_reminders_create_one_request__AC09_AC10(db, auth, reminder_world, same_key):
    from drugtime.main import create_app

    patient, family, _, schedule, at = reminder_world
    headers = auth(family)
    first_key = str(uuid4())
    keys = [first_key, first_key if same_key else str(uuid4())]
    barrier = Barrier(2)

    def send(key):
        with TestClient(create_app()) as test_client:
            barrier.wait(timeout=10)
            return test_client.post(
                f"/patients/{patient}/dose-reminders",
                headers=headers,
                json={"client_uuid": key, "schedule_id": schedule, "scheduled_at": at.isoformat()},
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(send, keys))

    assert sorted(response.status_code for response in responses) == (
        [200, 201] if same_key else [201, 429]
    ), [response.text for response in responses]
    assert (
        db.execute(
            text("SELECT count(*) FROM dose_reminder_requests WHERE sender_user_id = :family"),
            {"family": family},
        ).scalar_one()
        == 1
    )


def test_two_workers_cannot_claim_same_reminder__AC10_AC11(
    db, client, auth, reminder_world, role_engines
):
    from drugtime.modules.adherence.adapters.outbound.sql_patient_dose_reminders import (
        SqlPatientDoseReminders,
    )
    from drugtime.shared.db import SqlUnitOfWork

    patient, family, _, schedule, at = reminder_world
    response = client.post(
        f"/patients/{patient}/dose-reminders",
        headers=auth(family),
        json={"client_uuid": str(uuid4()), "schedule_id": schedule, "scheduled_at": at.isoformat()},
    )
    assert response.status_code == 201, response.text
    reminder_id = response.json()["id"]
    db.execute(
        text("UPDATE dose_reminder_outbox SET due_at = '1900-01-01 UTC' WHERE reminder_id = :id"),
        {"id": reminder_id},
    )
    barrier = Barrier(2)

    def claim(_):
        with role_engines["worker_role"].begin() as connection:
            barrier.wait(timeout=10)
            return SqlPatientDoseReminders().claim(SqlUnitOfWork(connection))

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, range(2)))
    assert sum(item is not None and item[0] == reminder_id for item in claims) == 1
    assert (
        db.execute(
            text("SELECT state FROM dose_reminder_outbox WHERE reminder_id = :id"),
            {"id": reminder_id},
        ).scalar_one()
        == "leased"
    )
    db.execute(
        text(
            "UPDATE dose_reminder_outbox SET state = 'done', lease_until = NULL "
            "WHERE reminder_id = :id"
        ),
        {"id": reminder_id},
    )


@pytest.mark.parametrize("change", ["revoked", "confirmed", "no_targets", "with_token"])
def test_worker_rechecks_eligibility_before_send__AC11_AC14(
    db, client, auth, reminder_world, role_engines, change, monkeypatch
):
    from drugtime.modules.adherence.adapters.outbound.other_modules import (
        AccessGuardAdapter,
        DeviceTokensAdapter,
        SchedulesAdapter,
    )
    from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlDoseLogs
    from drugtime.modules.adherence.adapters.outbound.sql_patient_dose_reminders import (
        SqlPatientDoseReminders,
    )
    from drugtime.modules.adherence.application.dispatch_patient_dose_reminders import (
        dispatch_reminders,
    )
    from drugtime.modules.adherence.domain.patient_dose_reminder import ReminderTransportResult
    from drugtime.shared.config import get_settings
    from drugtime.shared.db import SqlUnitOfWork, get_engine

    patient, family, link, schedule, at = reminder_world
    response = client.post(
        f"/patients/{patient}/dose-reminders",
        headers=auth(family),
        json={"client_uuid": str(uuid4()), "schedule_id": schedule, "scheduled_at": at.isoformat()},
    )
    assert response.status_code == 201, response.text
    reminder_id = response.json()["id"]
    db.execute(
        text("UPDATE dose_reminder_outbox SET due_at = '1970-01-01 UTC' WHERE reminder_id = :id"),
        {"id": reminder_id},
    )
    if change == "revoked":
        db.execute(
            text("UPDATE caregiver_links SET sharing_enabled = false WHERE id = :id"), {"id": link}
        )
    elif change == "confirmed":
        db.execute(
            text(
                "INSERT INTO dose_logs (medication_schedule_id, scheduled_at, taken_at, status) "
                "VALUES (:schedule, :at, :at, 'da_uong')"
            ),
            {"schedule": schedule, "at": at},
        )
    elif change == "with_token":
        db.execute(
            text(
                "INSERT INTO device_tokens (user_id, fcm_token, platform) "
                "VALUES (:patient, :token, 'android')"
            ),
            {"patient": patient, "token": f"test-{uuid4()}"},
        )

    @contextmanager
    def worker_uow():
        with role_engines["worker_role"].begin() as connection:
            yield SqlUnitOfWork(connection)

    notifier = Mock()

    def accepted(push):
        assert (
            sum(
                log["actor_user_id"] == family and log["result"] == "allowed" for log in make_logs()
            )
            > initial_allowed
        )
        return ReminderTransportResult(True)

    def make_logs():
        return [
            dict(row._mapping)
            for row in db.execute(
                text(
                    "SELECT actor_user_id, result FROM access_logs WHERE patient_user_id = :patient"
                ),
                {"patient": patient},
            )
        ]

    initial_allowed = sum(
        log["actor_user_id"] == family and log["result"] == "allowed" for log in make_logs()
    )
    notifier.send_reminder.side_effect = accepted
    # Model the worker process: the PEP's separate denied-log transaction uses this engine too.
    try:
        with monkeypatch.context() as environment:
            environment.setenv(
                "DATABASE_URL",
                role_engines["worker_role"].url.render_as_string(hide_password=False),
            )
            get_settings.cache_clear()
            get_engine.cache_clear()
            assert (
                dispatch_reminders(
                    worker_uow,
                    notifier=notifier,
                    access=AccessGuardAdapter(),
                    schedules=SchedulesAdapter(),
                    doses=SqlDoseLogs(),
                    tokens=DeviceTokensAdapter(),
                    store=SqlPatientDoseReminders(),
                    limit=1,
                )
                == 1
            )
    finally:
        if get_engine.cache_info().currsize:
            get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
    if change == "with_token":
        notifier.send_reminder.assert_called_once()
    else:
        notifier.send_reminder.assert_not_called()
    assert db.execute(
        text("SELECT status FROM dose_reminder_requests WHERE id = :id"), {"id": reminder_id}
    ).scalar_one() == (
        "accepted"
        if change == "no_targets"
        else "dispatched"
        if change == "with_token"
        else "cancelled"
    )
    if change == "revoked":
        assert any(
            log["actor_user_id"] == family and log["result"] == "denied" for log in make_logs()
        )
    if change == "confirmed":
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM dose_logs WHERE medication_schedule_id = :schedule "
                    "AND status = 'da_uong' AND taken_at = :at"
                ),
                {"schedule": schedule, "at": at},
            ).scalar_one()
            == 1
        )
