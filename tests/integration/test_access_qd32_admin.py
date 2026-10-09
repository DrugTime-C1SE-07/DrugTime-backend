"""QD-32 (task 2.04, AC22): admin không đọc hay ghi dữ liệu sức khỏe của người bệnh.

Mọi endpoint dùng access.authorize: thuốc (`danh_sach_thuoc`) và xác nhận liều
(`lich_su_tuan_thu`). Từ chối vẫn ghi access_logs `denied` với actor_role admin.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text


def test_admin_get_medication_403_denied__AC22(client, make, auth, scheduled_body):
    patient = make.user()
    med = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(patient)
    ).json()
    admin = make.user(admin=True)
    r = client.get(f"/medications/{med['id']}", headers=auth(admin))
    assert r.status_code == 403 and r.json() == {"detail": "khong_co_quyen"}
    assert "schedules" not in r.text
    assert make.access_logs(patient) == [
        {
            "actor_user_id": admin,
            "actor_role": "admin",
            "data_scope": "danh_sach_thuoc",
            "result": "denied",
            "rejection_reason": "khong_co_quyen",
        }
    ]


def test_admin_dose_batch_rejected__AC22(client, db, make, auth, scheduled_body):
    patient = make.user()
    med = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(patient)
    ).json()
    schedule_id = med["schedules"][0]["id"]
    admin = make.user(admin=True)
    at = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0)
    r = client.post(
        "/doses/batch",
        json=[
            {
                "client_uuid": str(uuid4()),
                "schedule_id": schedule_id,
                "scheduled_at": at.isoformat(),
                "taken_at": at.isoformat(),
            }
        ],
        headers=auth(admin),
    )
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["result"] == "failed"
    assert item["error"]["http_status"] == 403
    n = db.execute(
        text("SELECT count(*) FROM dose_logs WHERE medication_schedule_id = :s"), {"s": schedule_id}
    ).scalar_one()
    assert n == 0
    assert [
        (log["actor_role"], log["data_scope"], log["result"]) for log in make.access_logs(patient)
    ] == [("admin", "lich_su_tuan_thu", "denied")]
