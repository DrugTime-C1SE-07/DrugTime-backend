from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.adherence.adapters.inbound import http as notification_http
from drugtime.modules.adherence.adapters.inbound.http import NotificationType
from drugtime.modules.adherence.application.ports import Notifications
from drugtime.modules.adherence.domain.alert import NotificationRecord
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow
from drugtime.shared.errors import Forbidden


class FakeNotificationsRepo(Notifications):
    def __init__(self, records=None):
        self.records = records or []

    def create_missed_alert(self, uow, recipient_id, patient_id, dedupe_key, content=None):
        pass

    def metadata(self, uow, user_id, notification_id=None):
        return [
            (r.id, r.about_patient_user_id)
            for r in self.records
            if r.user_id == user_id and (notification_id is None or r.id == notification_id)
        ]

    def authorized_records(self, uow, user_id, ids):
        return [r for r in self.records if r.user_id == user_id and r.id in ids]

    def mark_as_read(self, uow, notification_id, user_id, is_read=True):
        for i, r in enumerate(self.records):
            if r.id == notification_id and r.user_id == user_id:
                updated = replace(r, is_read=is_read)
                self.records[i] = updated
                return updated
        return None

    def erase_for_user(self, uow, user_id):
        pass


@pytest.fixture
def current_user():
    return identity.CurrentUser(id=uuid4(), is_admin=False)


@pytest.fixture
def other_user():
    return identity.CurrentUser(id=uuid4(), is_admin=False)


@pytest.fixture
def sample_records(current_user, other_user):
    patient_id = uuid4()
    now = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)
    return [
        NotificationRecord(
            id=1,
            user_id=current_user.id,
            about_patient_user_id=patient_id,
            type=NotificationType.MISSED_DOSE_CARE_ALERT.value,
            content="Bác Nguyễn Văn A chưa ghi nhận liều thuốc lúc 08:00",
            is_read=False,
            created_at=now,
            about_patient_name="Nguyễn Văn A",
        ),
        NotificationRecord(
            id=2,
            user_id=current_user.id,
            about_patient_user_id=patient_id,
            type=NotificationType.MISSED_DOSE_CARE_ALERT.value,
            content="Bác Nguyễn Văn A chưa ghi nhận liều thuốc lúc 12:00",
            is_read=True,
            created_at=now,
            about_patient_name="Nguyễn Văn A",
        ),
        NotificationRecord(
            id=3,
            user_id=other_user.id,
            about_patient_user_id=patient_id,
            type=NotificationType.MISSED_DOSE_CARE_ALERT.value,
            content="Thông báo của user khác",
            is_read=False,
            created_at=now,
            about_patient_name="Người khác",
        ),
    ]


@pytest.fixture
def client(current_user, sample_records, monkeypatch):
    app = create_app()
    repo = FakeNotificationsRepo(list(sample_records))

    app.dependency_overrides[notification_http.notification_user] = lambda: current_user
    app.dependency_overrides[notification_http.get_notification_uow] = lambda: MagicMock()
    app.dependency_overrides[get_uow] = lambda: MagicMock()

    # Monkeypatch SqlNotifications in http.py to use fake repo
    monkeypatch.setattr(
        "drugtime.modules.adherence.adapters.inbound.http.SqlNotifications",
        lambda: repo,
    )
    monkeypatch.setattr(notification_http, "AccessGuardAdapter", MagicMock)
    monkeypatch.setattr(
        notification_http,
        "PatientNamesAdapter",
        lambda: MagicMock(get_patient_name=lambda *args: "Nguyễn Văn A"),
    )

    return TestClient(app)


def test_get_notifications_returns_user_inbox_with_counts(client, current_user):
    # AC6: GET /notifications trả về danh sách thông báo của user, kèm total và unread_count
    resp = client.get("/notifications")
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] == 2
    assert data["unread_count"] == 1
    assert len(data["items"]) == 2

    # Chỉ thấy thông báo của chính mình, không thấy thông báo id 3 của user khác
    ids = [item["id"] for item in data["items"]]
    assert ids == [1, 2]
    assert data["items"][0]["about_patient_name"] == "Nguyễn Văn A"


def test_get_notifications_filters_by_is_read_status(client):
    # AC6: GET /notifications?is_read=false chỉ trả về thông báo chưa đọc
    resp = client.get("/notifications?is_read=false")
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == 1
    assert data["items"][0]["is_read"] is False


def test_patch_notification_marks_as_read(client):
    # AC7: PATCH /notifications/{id} cập nhật is_read thành true
    resp = client.patch("/notifications/1", json={"is_read": True})
    assert resp.status_code == 200

    data = resp.json()
    assert data["id"] == 1
    assert data["is_read"] is True

    # Kiểm tra lại qua GET: số unread giảm về 0
    get_resp = client.get("/notifications?is_read=false")
    assert get_resp.json()["total"] == 0


def test_patch_notification_returns_404_for_other_users_notification(client):
    # AC7: Cố cập nhật thông báo của người khác (id=3) trả về 404
    resp = client.patch("/notifications/3", json={"is_read": True})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "notification_not_found"


def test_patch_notification_returns_404_for_nonexistent_notification(client):
    # AC7: Cố cập nhật thông báo không tồn tại trả về 404
    resp = client.patch("/notifications/999", json={"is_read": True})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "notification_not_found"


def test_notifications_endpoints_require_authentication():
    app = create_app()
    app.dependency_overrides[notification_http.get_notification_uow] = lambda: MagicMock()
    unauth_client = TestClient(app)
    for method, path, body in [
        ("GET", "/notifications", None),
        ("GET", "/notifications/1", None),
        ("PATCH", "/notifications/1", {"is_read": True}),
    ]:
        response = unauth_client.request(method, path, json=body)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/notifications", "get", None),
        ("/notifications/1", "get", None),
        ("/notifications/1", "patch", {"is_read": True}),
    ],
)
def test_no_store_success_and_validation(client, path, method, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    response = client.get("/notifications/0")
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


def test_detail_does_not_mark_read_and_legacy_fields_present(client):
    response = client.get("/notifications/1")
    assert response.status_code == 200
    assert response.json()["is_read"] is False
    assert response.json()["medication_name"] is None
    assert response.json()["scheduled_at"] is None


def test_revoked_is_denied_and_no_store(client, monkeypatch):
    def deny(*args):
        raise Forbidden("khong_co_quyen")

    monkeypatch.setattr(
        notification_http, "AccessGuardAdapter", lambda: MagicMock(authorize_adherence=deny)
    )
    assert client.get("/notifications").json() == {"items": [], "total": 0, "unread_count": 0}
    for method in ("get", "patch"):
        response = client.request(method, "/notifications/1", json={"is_read": True})
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"


def test_commit_failure_never_returns_health(client, monkeypatch):
    @contextmanager
    def fail_commit():
        yield MagicMock()
        raise RuntimeError("commit failed")

    client.app.dependency_overrides.pop(notification_http.get_notification_uow)
    monkeypatch.setattr(notification_http, "unit_of_work", fail_commit)
    response = client.patch("/notifications/1", json={"is_read": True})
    assert response.status_code == 503
    assert response.json() == {"detail": "notification_access_unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_post_update_name_lookup_failure_rolls_back_before_error_response(client, monkeypatch):
    events = []

    @contextmanager
    def transaction():
        try:
            yield MagicMock()
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    client.app.dependency_overrides.pop(notification_http.get_notification_uow)
    monkeypatch.setattr(notification_http, "unit_of_work", transaction)
    monkeypatch.setattr(
        notification_http,
        "PatientNamesAdapter",
        lambda: MagicMock(get_patient_name=MagicMock(side_effect=RuntimeError("lookup"))),
    )
    response = client.patch("/notifications/1", json={"is_read": True})
    assert response.status_code == 503
    assert events == ["rollback"]
    assert "content" not in response.json()


@pytest.mark.parametrize(
    "method,path,body,error_location,error_type",
    [
        ("GET", "/notifications?limit=0", None, ["query", "limit"], "greater_than_equal"),
        ("GET", "/notifications?limit=101", None, ["query", "limit"], "less_than_equal"),
        ("GET", "/notifications?offset=-1", None, ["query", "offset"], "greater_than_equal"),
        ("GET", "/notifications/0", None, ["path", "id"], "greater_than_equal"),
        (
            "PATCH",
            "/notifications/1",
            {"is_read": True, "patient_id": "unexpected"},
            ["body", "patient_id"],
            "extra_forbidden",
        ),
    ],
)
def test_validation_through_notification_uow_rolls_back_without_service_call(
    client, monkeypatch, method, path, body, error_location, error_type
):
    events = []

    @contextmanager
    def transaction():
        try:
            yield MagicMock()
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    # Keep the yield dependency: replacing it masks exception translation.
    client.app.dependency_overrides.pop(notification_http.get_notification_uow)
    monkeypatch.setattr(notification_http, "unit_of_work", transaction)
    services = []
    for name in ("list_my_notifications", "get_notification", "update_notification_status"):
        service = MagicMock(side_effect=AssertionError("invalid request reached service"))
        monkeypatch.setattr(notification_http, name, service)
        services.append(service)

    response = client.request(method, path, json=body)

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert any(
        error["loc"] == error_location and error["type"] == error_type
        for error in response.json()["detail"]
    )
    assert events == ["rollback"]
    for service in services:
        service.assert_not_called()
