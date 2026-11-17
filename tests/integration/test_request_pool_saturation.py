from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from test_meal_suggestions_api import install_fake_llm, log, meal_rows, suggest

from drugtime.main import create_app
from drugtime.modules.ai_meal.adapters.inbound import http as meal_http
from drugtime.modules.medication.adapters.inbound import profile_http
from drugtime.shared import db as shared_db


def test_profile_updates_complete_with_primary_pool_full(db, make, auth, monkeypatch):
    users = [make.user() for _ in range(3)]
    primary = create_engine(
        shared_db.get_engine().url,
        pool_size=3,
        max_overflow=0,
        pool_timeout=1,
    )
    monkeypatch.setattr(shared_db, "get_engine", lambda: primary)
    all_authenticated = Barrier(len(users), timeout=10)
    all_writes_finished = Barrier(len(users), timeout=10)
    real_uow = profile_http.unit_of_work

    @contextmanager
    def synchronized_write():
        all_authenticated.wait()
        try:
            with real_uow() as uow:
                yield uow
        finally:
            all_writes_finished.wait()

    monkeypatch.setattr(profile_http, "unit_of_work", synchronized_write)
    app = create_app()
    payload = {"full_name": "Pool QA", "date_of_birth": "1990-01-01", "gender": "nu"}

    def update(user):
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.put("/profile", json=payload, headers=auth(user)).status_code

    try:
        with ThreadPoolExecutor(max_workers=len(users)) as executor:
            assert list(executor.map(update, users)) == [204, 204, 204]
        for user in users:
            name = db.scalar(text("SELECT full_name FROM users WHERE id=:id"), {"id": user})
            assert name == payload["full_name"]
    finally:
        primary.dispose()

def test_meal_suggestions_denials_complete_with_primary_pool_full(db, make, auth, monkeypatch):
    patients = [make.user(consents=("health_data",)) for _ in range(3)]
    primary = create_engine(
        shared_db.get_engine().url,
        pool_size=3,
        max_overflow=0,
        pool_timeout=1,
    )
    monkeypatch.setattr(shared_db, "get_engine", lambda: primary)
    all_authenticated = Barrier(len(patients), timeout=10)
    all_finished = Barrier(len(patients), timeout=10)
    real_uow = meal_http.unit_of_work

    @contextmanager
    def synchronized_write():
        all_authenticated.wait()
        try:
            with real_uow() as uow:
                yield uow
        finally:
            all_finished.wait()

    monkeypatch.setattr(meal_http, "unit_of_work", synchronized_write)
    app = create_app()
    fake_llm = install_fake_llm(TestClient(app))

    def request(patient):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = suggest(client, auth, patient, patient)
            return response.status_code, response.json()

    try:
        with ThreadPoolExecutor(max_workers=len(patients)) as executor:
            assert list(executor.map(request, patients)) == [
                (403, {"detail": "consent_revoked"})
            ] * len(patients)
        for patient in patients:
            assert make.access_logs(patient) == [
                log(patient, "patient", "denied", "consent_revoked")
            ]
            assert meal_rows(db, patient) == []
        assert fake_llm.prompts == []
    finally:
        primary.dispose()
