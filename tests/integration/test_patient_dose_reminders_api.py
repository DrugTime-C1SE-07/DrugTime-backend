from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text


@pytest.fixture
def reminder_world(make, db):
    patient = make.user(consents=("health_data", "family_sharing"))
    family = make.user()
    link = make.link(patient, family, sharing=True)
    med = make.catalog_medication()
    rx = db.execute(
        text(
            "INSERT INTO prescriptions (user_id,entry_source) VALUES (:p,'mac_dinh') RETURNING id"
        ),
        {"p": patient},
    ).scalar_one()
    user_med = db.execute(
        text("""
        INSERT INTO user_medications (user_id,prescription_id,medication_id,entry_method,
        confirmation_status,quantity_per_dose,dosing_mode,doses_per_day)
        VALUES (:p,:rx,:m,'thu_cong','da_xac_nhan',1,'theo_gio',1) RETURNING id
    """),
        {"p": patient, "rx": rx, "m": med},
    ).scalar_one()
    at = (datetime.now(UTC) - timedelta(minutes=5)).replace(second=0, microsecond=0)
    local = at.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
    schedule = db.execute(
        text("""
        INSERT INTO medication_schedules
            (user_medication_id,intake_time,days_of_week,effective_from)
        VALUES (:m,:t,ARRAY[1,2,3,4,5,6,7]::smallint[],:effective) RETURNING id
    """),
        {
            "m": user_med,
            "t": local.time().replace(tzinfo=None),
            "effective": at - timedelta(days=1),
        },
    ).scalar_one()
    return patient, family, link, schedule, at


def test_reminder_replay_cooldown_and_received_inbox__AC09_AC10(client, db, auth, reminder_world):
    patient, family, _, schedule, at = reminder_world
    path = f"/patients/{patient}/dose-reminders"
    payload = {"client_uuid": str(uuid4()), "schedule_id": schedule, "scheduled_at": at.isoformat()}
    first = client.post(path, headers=auth(family), json=payload)
    assert first.status_code == 201, first.text
    replay = client.post(path, headers=auth(family), json=payload)
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    limited = client.post(path, headers=auth(family), json={**payload, "client_uuid": str(uuid4())})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert (
        db.execute(
            text("SELECT count(*) FROM dose_reminder_requests WHERE sender_user_id=:u"),
            {"u": family},
        ).scalar_one()
        == 1
    )
    inbox = client.get("/dose-reminders/received", headers=auth(patient))
    assert inbox.status_code == 200, inbox.text
    assert [i["id"] for i in inbox.json()["items"]] == [first.json()["id"]]
    assert client.get("/notifications", headers=auth(patient)).json()["items"] == []


def test_reminder_denied_after_sharing_disabled__AC14(client, db, auth, make, reminder_world):
    patient, family, link, schedule, at = reminder_world
    headers = auth(family)
    payload = {"client_uuid": str(uuid4()), "schedule_id": schedule, "scheduled_at": at.isoformat()}
    response = client.post(f"/patients/{patient}/dose-reminders", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    db.execute(text("UPDATE caregiver_links SET sharing_enabled=false WHERE id=:id"), {"id": link})
    replay = client.post(f"/patients/{patient}/dose-reminders", headers=headers, json=payload)
    assert replay.status_code == 403
    assert any(
        log["actor_user_id"] == family and log["result"] == "denied"
        for log in make.access_logs(patient)
    )


def test_reused_key_with_changed_occurrence_is_conflict__AC10(client, db, auth, reminder_world):
    patient, family, _, schedule, at = reminder_world
    path = f"/patients/{patient}/dose-reminders"
    payload = {"client_uuid": str(uuid4()), "schedule_id": schedule, "scheduled_at": at.isoformat()}
    first = client.post(path, headers=auth(family), json=payload)
    assert first.status_code == 201, first.text
    changed = client.post(
        path,
        headers=auth(family),
        json={**payload, "scheduled_at": (at - timedelta(days=1)).isoformat()},
    )
    assert changed.status_code == 409, changed.text
    assert (
        db.execute(
            text("SELECT count(*) FROM dose_reminder_requests WHERE sender_user_id = :u"),
            {"u": family},
        ).scalar_one()
        == 1
    )


def test_reminder_service_with_real_api_role__AC09(reminder_world):
    from drugtime.modules.adherence.adapters.outbound.other_modules import (
        AccessGuardAdapter,
        SchedulesAdapter,
    )
    from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlDoseLogs
    from drugtime.modules.adherence.adapters.outbound.sql_patient_dose_reminders import (
        SqlPatientDoseReminders,
    )
    from drugtime.modules.adherence.application.patient_dose_reminders import send_reminder
    from drugtime.modules.adherence.domain.patient_dose_reminder import ReminderCommand
    from drugtime.shared.db import unit_of_work

    patient, family, _, schedule, at = reminder_world
    with unit_of_work() as uow:
        receipt, created = send_reminder(
            uow,
            caller_id=family,
            caller_is_admin=False,
            patient_id=patient,
            cmd=ReminderCommand(uuid4(), schedule, at),
            access=AccessGuardAdapter(),
            schedules=SchedulesAdapter(),
            doses=SqlDoseLogs(),
            store=SqlPatientDoseReminders(),
        )
    assert created and receipt.patient_id == patient
