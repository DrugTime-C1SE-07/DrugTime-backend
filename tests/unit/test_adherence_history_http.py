from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.adherence.adapters.inbound import history_http as http
from drugtime.modules.adherence.domain.dose import DoseStatus
from drugtime.modules.adherence.domain.history import VIETNAM, HistoryRange, HistoryRow
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow
from drugtime.shared.errors import Forbidden

USER, PATIENT = uuid4(), uuid4()
NOW = datetime(2026, 10, 19, 12, tzinfo=VIETNAM)


@pytest.fixture
def client(monkeypatch):
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(USER, False)
    app.dependency_overrides[get_uow] = lambda: object()
    events = []

    @contextmanager
    def transaction():
        events.append("begin")
        yield object()
        events.append("commit")

    monkeypatch.setattr(http, "unit_of_work", transaction)
    monkeypatch.setattr(http, "now", lambda: NOW)
    monkeypatch.setattr(http, "_ACCESS", Mock())
    monkeypatch.setattr(http, "_READER", Mock(read=Mock(return_value=([], None))))
    result = TestClient(app, raise_server_exceptions=False)
    result.events = events
    return result


def test_http_auth_and_date_group_query_aliases_and_commit_before_response(client):
    response = client.get("/adherence?from=2026-10-01&to=2026-10-19")
    assert response.status_code == 200
    assert client.events == ["begin", "commit"]
    body = response.json()
    assert body["from"] == "2026-10-01" and body["to"] == "2026-10-19"
    assert body["patient_id"] == str(USER) and body["group_by"] == "date"
    assert body["summary"]["adherence_rate"] is None and body["groups"] == []
    assert body["summary"]["unverified"] == 0 and body["patient_last_synced_at"] is None
    assert "start" not in body and "end" not in body
    assert http._READER.read.call_args.args[1:] == (
        USER,
        HistoryRange(date(2026, 10, 1), NOW.date()),
        NOW,
    )


def test_http_medication_patient_selector_and_timestamp_precision(client):
    at = NOW.replace(hour=8, microsecond=123456)
    http._READER.read.return_value = (
        [HistoryRow(1, "Medicine", 7, at, at, DoseStatus.TAKEN)],
        None,
    )
    response = client.get(f"/adherence?patient_id={PATIENT}&group_by=medication")
    assert response.status_code == 200
    http._ACCESS.authorize_history.assert_called_once()
    assert http._ACCESS.authorize_history.call_args.args[1:] == (USER, False, PATIENT)
    body = response.json()
    assert body["group_by"] == "medication" and body["patient_id"] == str(PATIENT)
    dose = body["groups"][0]["doses"][0]
    assert dose["scheduled_at"] == dose["taken_at"] == "2026-10-19T08:00:00.123456+07:00"
    assert body["summary"]["adherence_rate"] == 100


@pytest.mark.parametrize(
    "query",
    [
        "from=2026-02-30",
        "from=19-10-2026",
        "from=2026-10-01T00:00:00",
        "from=1790899200",
        "from=20261001",
        "from=",
        "patient_id=bad",
        "group_by=other",
    ],
)
def test_invalid_query_has_existing_validation_array_and_never_reads(client, query):
    response = client.get(f"/adherence?{query}")
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    http._READER.read.assert_not_called()


@pytest.mark.parametrize(
    "query,error",
    [
        ("from=2026-10-19&to=2026-10-18", "invalid_adherence_date_range"),
        ("from=2026-07-21&to=2026-10-19", "adherence_range_too_large"),
        ("to=2026-10-20", "adherence_end_date_in_future"),
    ],
)
def test_invalid_cross_field_query_has_existing_detail_string(client, query, error):
    response = client.get(f"/adherence?{query}")
    assert response.status_code == 422 and response.json() == {"detail": error}
    http._READER.read.assert_not_called()


@pytest.mark.parametrize("consent_error", ["consent_revoked", "khong_co_quyen"])
def test_denied_no_health_read(client, consent_error):
    http._ACCESS.authorize_history.side_effect = Forbidden(consent_error)
    response = client.get("/adherence")
    assert response.status_code == 403 and response.json() == {"detail": consent_error}
    http._READER.read.assert_not_called()


def test_unauthenticated_does_not_read_health(monkeypatch):
    app = create_app()
    app.dependency_overrides[get_uow] = lambda: object()
    reader = Mock()
    monkeypatch.setattr(http, "_READER", reader)
    response = TestClient(app).get("/adherence")
    assert response.status_code == 401 and response.json() == {"detail": "Missing bearer token"}
    assert response.headers["cache-control"] == "no-store"
    reader.read.assert_not_called()


def test_early_missed_log_is_pending_at_exact_120(client):
    http._READER.read.return_value = (
        [HistoryRow(1, "Medicine", 7, NOW.replace(hour=10), None, DoseStatus.MISSED)],
        None,
    )
    response = client.get("/adherence")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["pending"] == 1 and body["summary"]["counted"] == 0
    dose = body["groups"][0]["doses"][0]
    assert (dose["status"], dose["status_source"], dose["taken_at"]) == (
        "cho_xac_nhan",
        "inferred",
        None,
    )


def test_existing_post_batch_route_unchanged(client, monkeypatch):
    from drugtime.modules.adherence.adapters.inbound import http as dose_http
    from drugtime.modules.adherence.domain.dose import (
        DoseConfirmationBatchResult,
        DoseConfirmationResult,
    )

    cid = uuid4()
    item = DoseConfirmationResult(cid, 7, NOW, "synced", 9, DoseStatus.TAKEN, True, NOW)
    monkeypatch.setattr(
        dose_http, "confirm_doses", Mock(return_value=DoseConfirmationBatchResult([item]))
    )
    response = client.post(
        "/doses/batch",
        json=[
            {
                "client_uuid": str(cid),
                "schedule_id": 7,
                "scheduled_at": NOW.isoformat(),
                "taken_at": NOW.isoformat(),
            }
        ],
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {"total": 1, "synced": 1, "failed": 0}
    assert response.json()["items"][0]["dose_status"] == "da_uong"
    assert "cache-control" not in response.headers


@pytest.mark.parametrize("failure", ["audit", "reader", "serialize", "commit"])
def test_internal_failure_never_returns_health_or_logs_private_exception(
    client, monkeypatch, caplog, failure
):
    private = "private-medication-and-database-details"
    if failure == "commit":

        @contextmanager
        def failed_commit():
            yield object()
            raise RuntimeError(private)

        monkeypatch.setattr(http, "unit_of_work", failed_commit)
    elif failure == "serialize":
        monkeypatch.setattr(
            http.AdherenceHistoryResponse, "model_validate", Mock(side_effect=ValueError(private))
        )
    elif failure == "audit":
        http._ACCESS.authorize_history.side_effect = RuntimeError(private)
    else:
        http._READER.read.side_effect = RuntimeError(private)
    response = client.get("/adherence")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["cache-control"] == "no-store"
    assert private not in response.text and private not in caplog.text
    if failure == "audit":
        http._READER.read.assert_not_called()


@pytest.mark.parametrize("status", [200, 403, 422, 500])
def test_all_error_statuses_have_no_store(client, status):
    path = "/adherence"
    if status == 403:
        http._ACCESS.authorize_history.side_effect = Forbidden("khong_co_quyen")
    elif status == 422:
        path += "?group_by=bad"
    elif status == 500:
        http._READER.read.side_effect = RuntimeError("unavailable")
    response = client.get(path)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
