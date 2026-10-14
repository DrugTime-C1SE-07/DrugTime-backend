from collections.abc import Iterator
from datetime import UTC, datetime
from socket import create_connection
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from drugtime.main import create_app
from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlNotifications
from drugtime.modules.adherence.domain.alert import dedupe_key
from drugtime.modules.identity import api as identity
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.config import get_settings
from drugtime.shared.db import unit_of_work


def _require_db() -> None:
    parsed = urlparse(get_settings().database_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    try:
        with create_connection((host, port), timeout=1):
            pass
    except OSError as exc:
        pytest.skip(f"local integration database is not available: {exc}")


@pytest.fixture(autouse=True)
def require_db() -> None:
    _require_db()


@pytest.fixture
def client_as() -> Iterator:
    app = create_app()

    def factory(user_id: UUID) -> TestClient:
        app.dependency_overrides[identity.current_user] = lambda: CurrentUser(
            id=user_id,
            is_admin=False,
        )
        return TestClient(app)

    yield factory
    app.dependency_overrides.clear()


def _seed_patient_caregiver_pair(
    patient_id: UUID | None = None,
    caregiver_id: UUID | None = None,
    sharing_enabled: bool = True,
    caregiver_platform: str = "android",
) -> tuple[UUID, UUID]:
    patient_id = patient_id or uuid4()
    caregiver_id = caregiver_id or uuid4()
    p_suffix = uuid4().hex
    c_suffix = uuid4().hex

    with unit_of_work() as uow:
        # 1. Tạo user bệnh nhân và người thân
        uow.connection.execute(
            text("""
            INSERT INTO users (id, email, full_name)
            VALUES (:pid, :pemail, :pname),
                   (:cid, :cemail, :cname)
            ON CONFLICT (id) DO NOTHING
            """),
            {
                "pid": patient_id,
                "pemail": f"patient-{p_suffix}@example.test",
                "pname": "Nguyễn Văn Bệnh Nhân",
                "cid": caregiver_id,
                "cemail": f"caregiver-{c_suffix}@example.test",
                "cname": "Trần Thị Người Thân",
            },
        )
        # 2. Cấp consent family_sharing cho bệnh nhân
        uow.connection.execute(
            text("""
            INSERT INTO user_consents (user_id, consent_type, status, document_version)
            VALUES (:uid, 'family_sharing', 'dong_y', 'test-v1')
            ON CONFLICT DO NOTHING
            """),
            {"uid": patient_id},
        )
        # 3. Tạo liên kết người thân
        uow.connection.execute(
            text("""
            INSERT INTO caregiver_links (patient_user_id, caregiver_user_id, status, sharing_enabled)
            VALUES (:pid, :cid, 'active', :sharing)
            """),
            {"pid": patient_id, "cid": caregiver_id, "sharing": sharing_enabled},
        )
        # 4. Tạo token thiết bị
        uow.connection.execute(
            text("""
            INSERT INTO device_tokens (user_id, fcm_token, platform)
            VALUES (:cid, :token, :platform)
            """),
            {
                "cid": caregiver_id,
                "token": f"token-{uuid4().hex}",
                "platform": caregiver_platform,
            },
        )
    return patient_id, caregiver_id


def test_integration_missed_dose_alert_dispatch_and_inbox_fetch__AC1_AC2_AC6(client_as):
    """AC1/AC2/AC6: Dispatch cảnh báo bỏ lỡ vào notifications và người thân đọc qua GET /notifications."""
    patient_id, caregiver_id = _seed_patient_caregiver_pair(caregiver_platform="android")
    dose_log_id = 998877

    notifications = SqlNotifications()
    with unit_of_work() as uow:
        nid = notifications.create_missed_alert(
            uow,
            recipient_id=caregiver_id,
            patient_id=patient_id,
            dedupe_key=dedupe_key(dose_log_id, caregiver_id),
            content="Bác Nguyễn Văn Bệnh Nhân chưa ghi nhận liều thuốc đúng giờ",
        )
        assert nid is not None

    # Người thân gọi GET /notifications
    client = client_as(caregiver_id)
    resp = client.get("/notifications")
    assert resp.status_code == 200

    body = resp.json()
    assert body["total"] >= 1
    assert body["unread_count"] >= 1
    found = [n for n in body["items"] if n["id"] == nid]
    assert len(found) == 1
    assert found[0]["content"] == "Bác Nguyễn Văn Bệnh Nhân chưa ghi nhận liều thuốc đúng giờ"
    assert found[0]["is_read"] is False
    assert found[0]["about_patient_user_id"] == str(patient_id)


def test_integration_caregiver_revocation_stops_alert_immediately__AC4():
    """AC4 (QA.02): Thu hồi liên kết / sharing_enabled=false thì không tạo notification."""
    patient_id, caregiver_id = _seed_patient_caregiver_pair(sharing_enabled=False)

    from drugtime.modules.access import api as access

    with unit_of_work() as uow:
        caregivers = access.authorized_caregivers(uow, patient_id)
        assert caregiver_id not in caregivers


def test_integration_patch_notification_marks_as_read__AC7(client_as):
    """AC7: PATCH /notifications/{id} cập nhật is_read=true."""
    patient_id, caregiver_id = _seed_patient_caregiver_pair()
    dose_log_id = 998878

    notifications = SqlNotifications()
    with unit_of_work() as uow:
        nid = notifications.create_missed_alert(
            uow,
            recipient_id=caregiver_id,
            patient_id=patient_id,
            dedupe_key=dedupe_key(dose_log_id, caregiver_id),
            content="Cảnh báo kiểm tra",
        )
        assert nid is not None

    client = client_as(caregiver_id)
    patch_resp = client.patch(f"/notifications/{nid}", json={"is_read": True})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_read"] is True

    # Người dùng khác cố patch thì nhận 404
    other_client = client_as(uuid4())
    forbidden_resp = other_client.patch(f"/notifications/{nid}", json={"is_read": True})
    assert forbidden_resp.status_code == 404
