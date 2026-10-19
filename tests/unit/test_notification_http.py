from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.adherence.adapters.inbound.http import NotificationType
from drugtime.modules.adherence.application.ports import Notifications
from drugtime.modules.adherence.domain.alert import NotificationRecord
from drugtime.modules.identity import api as identity
from drugtime.shared.db import get_uow


class FakeNotificationsRepo(Notifications):
    def __init__(self, records=None):
        self.records = records or []

    def create_missed_alert(self, uow, recipient_id, patient_id, dedupe_key, content=None):
        pass

    def list_for_user(self, uow, user_id, is_read, limit, offset):
        matched = [r for r in self.records if r.user_id == user_id]
        if is_read is not None:
            matched = [r for r in matched if r.is_read == is_read]
        unread = sum(1 for r in self.records if r.user_id == user_id and not r.is_read)
        paged = matched[offset : offset + limit]
        return paged, len(matched), unread

    def mark_as_read(self, uow, notification_id, user_id, is_read=True):
        for i, r in enumerate(self.records):
            if r.id == notification_id and r.user_id == user_id:
                updated = NotificationRecord(
                    id=r.id,
                    user_id=r.user_id,
                    about_patient_user_id=r.about_patient_user_id,
                    type=r.type,
                    content=r.content,
                    is_read=is_read,
                    created_at=r.created_at,
                    about_patient_name=r.about_patient_name,
                )
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

    app.dependency_overrides[identity.current_user] = lambda: current_user
    app.dependency_overrides[get_uow] = lambda: MagicMock()

    # Monkeypatch SqlNotifications in http.py to use fake repo
    monkeypatch.setattr(
        "drugtime.modules.adherence.adapters.inbound.http.SqlNotifications",
        lambda: repo,
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
    # AC6/AC7: Không có token authentication trả về 401
    unauth_client = TestClient(create_app())
    assert unauth_client.get("/notifications").status_code == 401
    assert unauth_client.patch("/notifications/1", json={"is_read": True}).status_code == 401
