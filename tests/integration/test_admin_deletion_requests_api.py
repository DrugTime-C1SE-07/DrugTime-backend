"""Acceptance tests for the Admin deletion queue against local PostgreSQL."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from drugtime.modules.consent.adapters.inbound import http
from drugtime.modules.consent.adapters.outbound import job_queue
from drugtime.modules.identity.application.sign_in import issue_app_session
from drugtime.modules.identity.domain.user import SessionType

PATH = "/admin/deletion-requests"
SENT_AT = datetime(2026, 10, 1, 1, tzinfo=UTC)


@pytest.fixture
def create_request(db, make, admin_auth):
    admin_id, _ = admin_auth
    created = []

    def insert(status="cho_duyet", *, requested_at=SENT_AT, user_id=None):
        request_id = db.execute(
            text(
                """
                INSERT INTO data_deletion_requests (
                    user_id, status, requested_at, handled_by_admin_id,
                    handled_at, completed_at, rejection_reason
                )
                VALUES (:user_id, CAST(:status AS deletion_status), :requested_at, :admin_id,
                        :handled_at, :completed_at, :rejection_reason)
                RETURNING id
                """
            ),
            {
                "user_id": user_id if user_id is not None else make.user(consents=()),
                "status": status,
                "requested_at": requested_at,
                "admin_id": None if status == "cho_duyet" else admin_id,
                "handled_at": None if status == "cho_duyet" else requested_at,
                "completed_at": requested_at if status == "hoan_tat" else None,
                "rejection_reason": "Test rejection" if status == "tu_choi" else None,
            },
        ).scalar_one()
        created.append(request_id)
        return request_id

    yield insert

    for request_id in created:
        db.execute(text("DELETE FROM data_deletion_requests WHERE id = :id"), {"id": request_id})


def _page(client, headers, **params):
    response = client.get(PATH, headers=headers, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert set(payload) == {"items", "total"}
    return payload


def test_pending_queue_filters_orders_and_paginates__AC1_AC6(
    client, make, admin_auth, create_request
):
    _, headers = admin_auth
    later = create_request(requested_at=SENT_AT + timedelta(hours=1))
    patient = make.user(consents=())
    first = create_request(user_id=patient)
    second = create_request()
    for status in ("da_duyet", "tu_choi", "hoan_tat"):
        create_request(status)

    page = _page(client, headers, limit=2)
    assert page["total"] == 3
    assert [item["id"] for item in page["items"]] == [first, second]
    assert page["items"][0] == {
        "id": first,
        "user_id": str(patient),
        "requested_at": "2026-10-01T08:00:00+07:00",
        "status": "cho_duyet",
    }
    for item in page["items"]:
        assert set(item) == {"id", "user_id", "requested_at", "status"}
        assert item["status"] == "cho_duyet"
    assert [item["id"] for item in _page(client, headers, skip=2, limit=1)["items"]] == [later]
    assert _page(client, headers, skip=3) == {"items": [], "total": 3}
    assert _page(client, headers, skip=2**70) == {"items": [], "total": 3}


@pytest.mark.parametrize("status", ["da_duyet", "tu_choi"])
def test_pending_queue_reflects_committed_transition__AC2(
    client, db, admin_auth, create_request, status
):
    admin_id, headers = admin_auth
    request_id = create_request()
    assert [item["id"] for item in _page(client, headers)["items"]] == [request_id]

    db.execute(
        text(
            """
            UPDATE data_deletion_requests
            SET status = CAST(:status AS deletion_status), handled_by_admin_id = :admin_id,
                handled_at = :handled_at, rejection_reason = :reason
            WHERE id = :id
            """
        ),
        {
            "id": request_id,
            "status": status,
            "admin_id": admin_id,
            "handled_at": SENT_AT,
            "reason": "Test rejection" if status == "tu_choi" else None,
        },
    )
    assert _page(client, headers) == {"items": [], "total": 0}


def test_pending_queue_shows_recorded_deletion_but_not_withdrawal__AC3(
    client, db, make, auth, admin_auth, create_request
):
    _, headers = admin_auth
    patient = make.user(consents=("ai_meal",))
    before = _page(client, headers)
    withdrawn = client.post("/consents/ai_meal/withdraw", headers=auth(patient))
    assert withdrawn.status_code == 200, withdrawn.text
    assert _page(client, headers) == before

    recorded_at = db.execute(text("SELECT clock_timestamp()")).scalar_one()
    request_id = create_request(user_id=patient, requested_at=recorded_at)
    page = _page(client, headers)
    checked_at = db.execute(text("SELECT clock_timestamp()")).scalar_one()
    assert page["total"] == before["total"] + 1
    assert request_id in {item["id"] for item in page["items"]}
    assert timedelta(0) <= checked_at - recorded_at <= timedelta(seconds=60)


def test_pending_queue_requires_current_admin__AC5(
    client, db, make, auth, admin_auth, create_request
):
    admin_id, headers = admin_auth
    request_id = create_request()
    patient = make.user()
    family = make.user()
    make.pending_link(patient, family)
    assert _page(client, headers)["items"][0]["id"] == request_id

    expired = issue_app_session(
        admin_id, SessionType.ADMIN_WEB, datetime.now(UTC) - timedelta(hours=1)
    ).token
    for credentials in (
        {},
        {"Authorization": "Bearer invalid"},
        {"Authorization": f"Bearer {expired}"},
    ):
        response = client.get(PATH, headers=credentials)
        assert response.status_code == 401
        assert set(response.json()) == {"detail"}
    for user in (patient, family):
        response = client.get(PATH, headers=auth(user))
        assert (response.status_code, response.json()) == (403, {"detail": "admin_only"})

    db.execute(text("UPDATE users SET system_role = 'user' WHERE id = :id"), {"id": admin_id})
    denied = client.get(PATH, headers=headers)
    assert (denied.status_code, denied.json()) == (403, {"detail": "admin_only"})


def test_pending_queue_read_only_and_handles_database_failure__AC4(
    client, db, admin_auth, create_request, monkeypatch
):
    _, headers = admin_auth
    request_id = create_request()
    statement = text("SELECT * FROM data_deletion_requests WHERE id = :id")
    before = db.execute(statement, {"id": request_id}).one()
    with patch.object(job_queue, "enqueue_erasure") as enqueue:
        assert _page(client, headers) == _page(client, headers)
        for obj, attribute in (
            (http, "unit_of_work"),
            (http.identity, "current_user"),
            (http.SqlDeletionRequests, "list_pending"),
        ):
            with monkeypatch.context() as patches:
                patches.setattr(obj, attribute, _raise_database_error)
                response = client.get(PATH, headers=headers)
                assert (response.status_code, response.json()) == (
                    503,
                    {"detail": "service_unavailable"},
                )
        enqueue.assert_not_called()
    assert db.execute(statement, {"id": request_id}).one() == before


def _raise_database_error(*args, **kwargs):
    raise SQLAlchemyError("Injected failure")


@pytest.mark.parametrize(
    "query",
    ["?skip=-1", "?skip=word", "?limit=0", "?limit=101", "?skip=0&skip=0", "?user_id=unknown"],
)
def test_pending_queue_rejects_invalid_query(client, admin_auth, query):
    _, headers = admin_auth
    response = client.get(PATH + query, headers=headers)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_pending_queue_rejects_get_body(client, admin_auth):
    _, headers = admin_auth
    response = client.request("GET", PATH, headers=headers, json={})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_pending_queue_accepts_query_boundaries(client, admin_auth, create_request):
    _, headers = admin_auth
    create_request()
    assert len(_page(client, headers, skip=0, limit=1)["items"]) == 1
    assert _page(client, headers, skip=1, limit=100) == {"items": [], "total": 1}
