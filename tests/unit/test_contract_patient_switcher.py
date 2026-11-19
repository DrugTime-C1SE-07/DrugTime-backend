import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.adherence.adapters.inbound import patient_dose_reminders_http as http
from drugtime.modules.identity import api as identity
from drugtime.modules.medication.adapters.inbound import http as medication_http
from drugtime.shared.errors import Forbidden, TooManyRequests
from tests.unit.test_contract_medication import _request, _response, _shape

CANONICAL = json.loads(
    (Path(__file__).resolve().parents[3] / "api_contract/openapi.json").read_text(encoding="utf-8")
)
PATHS = [
    ("/patients/{patient_id}/medications", "get"),
    ("/patients/{patient_id}/dose-reminders", "post"),
    ("/patients/{patient_id}/dose-reminders/status", "get"),
    ("/dose-reminders/received", "get"),
    ("/dose-reminders/received/{id}", "get"),
    ("/dose-reminders/received/{id}", "patch"),
]


@pytest.mark.parametrize("path,method", PATHS)
def test_new_operations_match_canonical_security_and_statuses(path, method):
    spec = create_app().openapi()
    actual = spec["paths"][path][method]
    expected = CANONICAL["paths"][path][method]
    assert actual["operationId"] == expected["operationId"]
    assert actual["security"] == expected["security"]
    assert set(actual["responses"]) == set(expected["responses"])
    assert actual["x-health-audit-self"] is True
    for code in expected["responses"]:
        if code.startswith("2"):
            assert _shape(spec, _response(spec, actual, code)) == _shape(
                CANONICAL, _response(CANONICAL, expected, code)
            )
    if "requestBody" in expected:
        assert _shape(spec, _request(spec, actual)) == _shape(
            CANONICAL, _request(CANONICAL, expected)
        )


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )
    app.dependency_overrides[http.reminder_uow] = lambda: Mock()
    app.dependency_overrides[medication_http.get_patient_medication_uow] = lambda: Mock()
    return TestClient(app)


def test_new_reminder_validation_and_cooldown_have_no_store(client, monkeypatch):
    patient = str(uuid4())
    path = f"/patients/{patient}/dose-reminders"
    assert client.post(path, json={}).headers["cache-control"] == "no-store"
    monkeypatch.setattr(
        http, "send_reminder", Mock(side_effect=TooManyRequests("reminder_cooldown", 9))
    )
    response = client.post(
        path,
        json={
            "client_uuid": str(uuid4()),
            "schedule_id": 1,
            "scheduled_at": "2026-11-19T08:30:00+07:00",
        },
    )
    assert response.status_code == 429 and response.headers["retry-after"] == "9"
    assert response.headers["cache-control"] == "no-store"


def test_patient_medication_denial_and_commit_failure_never_return_health(client, monkeypatch):
    monkeypatch.setattr(
        medication_http,
        "list_linked_patient_medications",
        Mock(side_effect=Forbidden("khong_co_quyen")),
    )
    response = client.get(f"/patients/{uuid4()}/medications")
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"


def test_reminder_audit_commit_failure_returns_generic_503(monkeypatch):
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )

    @contextmanager
    def broken():
        yield Mock()
        raise RuntimeError("commit unavailable")

    monkeypatch.setattr(http, "unit_of_work", broken)
    monkeypatch.setattr(http, "received_list", lambda *a, **k: ([], 0, 0))
    response = TestClient(app).get("/dose-reminders/received")
    assert response.status_code == 503
    assert response.json() == {"detail": "service_unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_medication_audit_commit_failure_returns_generic_503(monkeypatch):
    from drugtime.modules.medication.application.list_linked_patient_medications import (
        PatientMedicationPage,
    )

    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
        id=uuid4(), is_admin=False
    )

    @contextmanager
    def broken():
        yield Mock()
        raise RuntimeError("commit unavailable")

    monkeypatch.setattr(medication_http, "unit_of_work", broken)
    monkeypatch.setattr(
        medication_http,
        "list_linked_patient_medications",
        lambda *a, **k: PatientMedicationPage([], None),
    )
    response = TestClient(app).get(f"/patients/{uuid4()}/medications")
    assert response.status_code == 503
    assert response.json() == {"detail": "service_unavailable"}
    assert response.headers["cache-control"] == "no-store"
