"""Integration tests cho chốt chặn PEP khi tài khoản đang chờ xóa (cho_xoa).

Phủ AC6, AC7, AC8 và các kịch bản chất lượng:
- Chính chủ đang `cho_xoa` bị chặn 403 `account_pending_deletion` trên mọi endpoint
  dữ liệu sức khỏe và đồng bộ, có dòng `denied` trong `access_logs` (transaction riêng).
- Người thân liên kết hợp lệ vẫn nhận 403 `khong_co_quyen` + dòng `denied`
  (không lộ trạng thái xóa).
- Các endpoint quản lý xóa (`/data-deletion-requests/current`, `/current/cancel`) vẫn hoạt động.
- Hủy yêu cầu xóa khôi phục quyền cho chính chủ ngay ở request kế tiếp (không cache quyền).
- `POST /doses/batch` rollback toàn bộ mẻ khi trả 403 `account_pending_deletion` nhưng vẫn giữ
  dòng `denied` trong `access_logs`.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_meal_suggestions_api import BODY as MEAL_BODY
from test_meal_suggestions_api import disable_real_llm, install_fake_llm, meal_rows

from drugtime.shared.config import get_settings

BASE_DELETION = "/data-deletion-requests"


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    disable_real_llm(monkeypatch)
    yield
    get_settings.cache_clear()


def _mark_pending_deletion(db, user_id) -> None:
    db.execute(
        text(
            "INSERT INTO data_deletion_requests "
            "(user_id, requested_at, scheduled_deletion_at) "
            "VALUES (:u, now(), now() + interval '720 hours')"
        ),
        {"u": user_id},
    )


def _create_medication_and_schedule(client, auth, make, scheduled_body, patient_id):
    med_id = make.catalog_medication()
    resp = client.post(
        "/medications",
        headers=auth(patient_id),
        json=scheduled_body(med_id),
    )
    assert resp.status_code == 201, resp.text
    user_med_id = resp.json()["id"]
    schedule_id = make.schedules(user_med_id)[0]["id"]
    return user_med_id, schedule_id


def test_pending_deletion_blocks_owner_health_and_sync_endpoints_with_denied_audit__AC6(
    client, db, make, auth, scheduled_body
):
    llm = install_fake_llm(client)
    patient = make.user(consents=("health_data", "ai_meal"))
    user_med_id, schedule_id = _create_medication_and_schedule(
        client, auth, make, scheduled_body, patient
    )
    before_counts = make.counts(patient)
    before_logs = len(make.access_logs(patient))

    _mark_pending_deletion(db, patient)

    headers = auth(patient)
    scheduled_at = datetime(2026, 11, 22, 1, 0, tzinfo=UTC).isoformat()
    taken_at = datetime(2026, 11, 22, 1, 5, tzinfo=UTC).isoformat()

    calls = [
        ("GET", "/medications", None),
        ("POST", "/medications", scheduled_body(make.catalog_medication())),
        ("GET", "/profile", None),
        ("GET", "/adherence", None),
        ("GET", "/dose-reminders/received", None),
        ("POST", "/doses/sync-checkpoints", None),
        (
            "POST",
            "/doses/batch",
            [
                {
                    "client_uuid": str(uuid4()),
                    "schedule_id": schedule_id,
                    "scheduled_at": scheduled_at,
                    "taken_at": taken_at,
                }
            ],
        ),
        ("POST", f"/patients/{patient}/meal-suggestions", MEAL_BODY),
    ]

    for method, path, payload in calls:
        resp = client.request(method, path, headers=headers, json=payload)
        assert (resp.status_code, resp.json()) == (
            403,
            {"detail": "account_pending_deletion"},
        ), f"{method} {path} -> {resp.status_code} {resp.text}"

    assert make.counts(patient) == before_counts
    assert make.dose_logs_of(user_med_id) == []
    assert llm.prompts == []
    assert meal_rows(db, patient) == []

    new_logs = make.access_logs(patient)[before_logs:]
    assert len(new_logs) >= len(calls)
    assert all(
        row["actor_user_id"] == patient
        and row["actor_role"] == "patient"
        and row["result"] == "denied"
        and row["rejection_reason"] == "account_pending_deletion"
        for row in new_logs
    )


def test_pending_deletion_allows_deletion_management_endpoints__AC6_AC8(
    client, db, make, auth
):
    patient = make.user()
    _mark_pending_deletion(db, patient)
    headers = auth(patient)

    current = client.get(f"{BASE_DELETION}/current", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["status"] == "cho_xoa"

    cancelled = client.post(f"{BASE_DELETION}/current/cancel", headers=headers)
    assert cancelled.status_code == 204, cancelled.text

    after = client.get(f"{BASE_DELETION}/current", headers=headers)
    assert after.status_code == 200 and after.json() is None


def test_pending_deletion_denies_linked_family_with_khong_co_quyen_and_audit__AC7(
    client, db, make, auth, scheduled_body
):
    patient = make.user()
    family = make.family_of(patient)
    _create_medication_and_schedule(client, auth, make, scheduled_body, patient)

    assert client.get(f"/patients/{patient}/schedules", headers=auth(family)).status_code == 200

    _mark_pending_deletion(db, patient)
    before_logs = len(make.access_logs(patient))

    for path in (
        f"/patients/{patient}/schedules",
        f"/adherence?patient_id={patient}",
    ):
        resp = client.get(path, headers=auth(family))
        assert (resp.status_code, resp.json()) == (
            403,
            {"detail": "khong_co_quyen"},
        ), f"GET {path} -> {resp.status_code} {resp.text}"

    new_logs = make.access_logs(patient)[before_logs:]
    assert len(new_logs) == 2
    assert all(
        row["actor_user_id"] == family
        and row["actor_role"] == "family"
        and row["result"] == "denied"
        and row["rejection_reason"] == "khong_co_quyen"
        for row in new_logs
    )


def test_cancel_deletion_restores_owner_health_and_sync_immediately__AC8(
    client, db, make, auth, scheduled_body
):
    patient = make.user()
    user_med_id, schedule_id = _create_medication_and_schedule(
        client, auth, make, scheduled_body, patient
    )
    headers = auth(patient)

    _mark_pending_deletion(db, patient)
    assert client.get("/medications", headers=headers).status_code == 403
    assert client.post("/doses/sync-checkpoints", headers=headers).status_code == 403

    assert client.post(f"{BASE_DELETION}/current/cancel", headers=headers).status_code == 204

    assert client.get("/medications", headers=headers).status_code == 200
    assert client.post("/doses/sync-checkpoints", headers=headers).status_code == 204

    scheduled_at = datetime(2026, 11, 22, 1, 0, tzinfo=UTC).isoformat()
    taken_at = datetime(2026, 11, 22, 1, 5, tzinfo=UTC).isoformat()
    batch = client.post(
        "/doses/batch",
        headers=headers,
        json=[
            {
                "client_uuid": str(uuid4()),
                "schedule_id": schedule_id,
                "scheduled_at": scheduled_at,
                "taken_at": taken_at,
            }
        ],
    )
    assert batch.status_code == 200, batch.text
    assert len(make.dose_logs_of(user_med_id)) == 1


def test_pending_deletion_batch_rolls_back_all_items_on_403__AC6(
    client, db, make, auth, scheduled_body
):
    patient = make.user()
    user_med_id, schedule_id = _create_medication_and_schedule(
        client, auth, make, scheduled_body, patient
    )
    headers = auth(patient)

    _mark_pending_deletion(db, patient)
    before_logs = len(make.access_logs(patient))

    base_time = datetime(2026, 11, 22, 1, 0, tzinfo=UTC)
    payload = [
        {
            "client_uuid": str(uuid4()),
            "schedule_id": schedule_id,
            "scheduled_at": (base_time + timedelta(days=i)).isoformat(),
            "taken_at": (base_time + timedelta(days=i, minutes=5)).isoformat(),
        }
        for i in range(3)
    ]

    resp = client.post("/doses/batch", headers=headers, json=payload)
    assert (resp.status_code, resp.json()) == (403, {"detail": "account_pending_deletion"})
    assert make.dose_logs_of(user_med_id) == []

    new_logs = make.access_logs(patient)[before_logs:]
    assert len(new_logs) >= 1
    assert any(
        row["actor_user_id"] == patient
        and row["result"] == "denied"
        and row["rejection_reason"] == "account_pending_deletion"
        for row in new_logs
    )
