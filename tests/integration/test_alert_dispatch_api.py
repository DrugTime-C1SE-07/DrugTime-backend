from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from socket import create_connection
from time import perf_counter
from urllib.parse import urlparse
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from drugtime.main import create_app
from drugtime.modules.adherence.adapters.outbound.sql_adherence import SqlNotifications
from drugtime.modules.adherence.domain.alert import dedupe_key
from drugtime.modules.identity import api as identity
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.config import get_settings
from drugtime.shared.db import SqlUnitOfWork, unit_of_work


@contextmanager
def _admin_uow(admin_engine):
    with admin_engine.begin() as connection:
        yield SqlUnitOfWork(connection)


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
    admin_engine,
    patient_id: UUID | None = None,
    caregiver_id: UUID | None = None,
    sharing_enabled: bool = True,
    caregiver_platform: str = "android",
) -> tuple[UUID, UUID]:
    patient_id = patient_id or uuid4()
    caregiver_id = caregiver_id or uuid4()
    p_suffix = uuid4().hex
    c_suffix = uuid4().hex

    with _admin_uow(admin_engine) as uow:
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
            INSERT INTO caregiver_links (patient_user_id, family_user_id, status, sharing_enabled)
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


def test_integration_missed_dose_alert_dispatch_and_inbox_fetch__AC1_AC2_AC6(client_as, admin_engine):
    """AC1/AC2/AC6: Dispatch cảnh báo bỏ lỡ vào notifications và người thân đọc qua GET /notifications."""
    patient_id, caregiver_id = _seed_patient_caregiver_pair(admin_engine, caregiver_platform="android")
    dose_log_id = 998877
    scheduled_at = datetime(2026, 10, 19, 8, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    notifications = SqlNotifications()
    with _admin_uow(admin_engine) as uow:
        nid = notifications.create_missed_alert(
            uow,
            recipient_id=caregiver_id,
            patient_id=patient_id,
            dedupe_key=dedupe_key(dose_log_id, caregiver_id),
            content="Bác Nguyễn Văn Bệnh Nhân chưa ghi nhận liều thuốc đúng giờ",
            medication_name="Integration medicine",
            scheduled_at=scheduled_at,
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


def test_integration_caregiver_revocation_stops_alert_immediately__AC4(admin_engine):
    """AC4 (QA.02): Thu hồi liên kết / sharing_enabled=false thì không tạo notification."""
    patient_id, caregiver_id = _seed_patient_caregiver_pair(admin_engine, sharing_enabled=False)

    from drugtime.modules.access import api as access

    with unit_of_work() as uow:
        caregivers = access.authorized_caregivers(uow, patient_id)
        assert caregiver_id not in caregivers


def test_integration_patch_notification_marks_as_read__AC7(client_as, admin_engine):
    """AC7: PATCH /notifications/{id} cập nhật is_read=true."""
    patient_id, caregiver_id = _seed_patient_caregiver_pair(admin_engine)
    dose_log_id = 998878
    scheduled_at = datetime(2026, 10, 19, 9, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    notifications = SqlNotifications()
    with _admin_uow(admin_engine) as uow:
        nid = notifications.create_missed_alert(
            uow,
            recipient_id=caregiver_id,
            patient_id=patient_id,
            dedupe_key=dedupe_key(dose_log_id, caregiver_id),
            content="Cảnh báo kiểm tra",
            medication_name="Integration medicine",
            scheduled_at=scheduled_at,
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


def test_integration_alert_timing_and_naming_flow(client_as, admin_engine):
    """AC8 / QD-25 / NFR05: Đo thời gian dispatch và truy vấn trên Postgres thật < 2s, kiểm tra tên bệnh nhân."""
    patient_id, caregiver_id = _seed_patient_caregiver_pair(admin_engine, caregiver_platform="android")
    dose_log_id = 998879
    scheduled_at = datetime(2026, 10, 19, 10, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    start_time = perf_counter()

    notifications = SqlNotifications()
    with _admin_uow(admin_engine) as uow:
        nid = notifications.create_missed_alert(
            uow,
            recipient_id=caregiver_id,
            patient_id=patient_id,
            dedupe_key=dedupe_key(dose_log_id, caregiver_id),
            content="Bác Nguyễn Văn Bệnh Nhân chưa ghi nhận liều thuốc đúng giờ",
            medication_name="Integration medicine",
            scheduled_at=scheduled_at,
        )
        assert nid is not None

    client = client_as(caregiver_id)
    resp = client.get("/notifications")
    assert resp.status_code == 200

    elapsed = perf_counter() - start_time

    # Khẳng định thời gian hoàn tất trên Postgres thật đạt SLO < 2.0 giây
    assert elapsed < 2.0, f"Dispatch & query time exceeded SLO: {elapsed:.4f}s"

    body = resp.json()
    items = [n for n in body["items"] if n["id"] == nid]
    assert len(items) == 1
    assert items[0]["content"] == "Bác Nguyễn Văn Bệnh Nhân chưa ghi nhận liều thuốc đúng giờ"
    assert items[0]["about_patient_user_id"] == str(patient_id)
    assert items[0]["is_read"] is False

