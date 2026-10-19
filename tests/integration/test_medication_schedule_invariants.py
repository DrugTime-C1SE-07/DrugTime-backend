"""Bất biến lịch uống trên chuỗi thao tác ngẫu nhiên, seed cố định (task 2.04, AC30).

Mỗi chuỗi chạy 10 bước trên một thuốc theo giờ: thêm, sửa, xóa từng lịch, bật/tắt nhắc, đổi
giờ, đổi ngày, ngừng, dùng lại, chuyển chế độ, liều xác nhận sớm. Sau mỗi bước:

  I1  không giờ dự kiến nào thuộc hai lịch cùng giờ của một thuốc;
  I2  mọi liều đã ghi nằm trong khoảng hiệu lực [effective_from, ended_at) của lịch nó trỏ tới;
  I3  thuốc khi cần hoặc đã ngừng không có lịch mở;
  I4  thuốc theo giờ đang dùng có >= 1 lịch mở, giờ không trùng, doses_per_day = số lịch mở;
  I5  không request nào trả 5xx.

Seed 43, 96, 97, 178, 198 là các chuỗi đã tìm ra R3 ở review vòng 4.
"""

import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

TIMES = ["07:00", "07:55", "08:00", "12:00", "20:00", "22:00"]
OPS = [
    "early",
    "early",
    "edit_time",
    "toggle",
    "days",
    "add",
    "remove",
    "stop",
    "unstop",
    "as_needed",
    "scheduled",
    "times",
]
SEEDS = [*range(50), 96, 97, 178, 198]  # range(50) đã gồm 43


def _state(db, med_id):
    med = db.execute(
        text(
            "SELECT dosing_mode::text AS mode, ended_at, doses_per_day "
            "FROM user_medications WHERE id = :i"
        ),
        {"i": med_id},
    ).one()
    rows = db.execute(
        text(
            "SELECT id, to_char(intake_time, 'HH24:MI') AS t, effective_from, ended_at "
            "FROM medication_schedules WHERE user_medication_id = :i ORDER BY id"
        ),
        {"i": med_id},
    ).all()
    doses = db.execute(
        text(
            "SELECT dl.medication_schedule_id AS s, dl.scheduled_at AS at FROM dose_logs dl "
            "JOIN medication_schedules ms ON ms.id = dl.medication_schedule_id "
            "WHERE ms.user_medication_id = :i"
        ),
        {"i": med_id},
    ).all()
    return med, rows, doses


def _check(db, med_id, where):
    med, rows, doses = _state(db, med_id)
    by_time = {}
    for r in rows:
        by_time.setdefault(r.t, []).append(r)
    for t, same in by_time.items():
        same = sorted(same, key=lambda r: (r.effective_from, r.id))
        for a, b in zip(same, same[1:], strict=False):
            assert a.ended_at is not None and a.ended_at <= b.effective_from, ("I1", where, t)
    by_id = {r.id: r for r in rows}
    for d in doses:
        s = by_id[d.s]
        inside = s.effective_from <= d.at and (s.ended_at is None or d.at < s.ended_at)
        assert inside, ("I2", where, d.at, s)
    opened = [r for r in rows if r.ended_at is None]
    if med.mode == "khi_can" or med.ended_at is not None:
        assert opened == [], ("I3", where, med.mode)
    else:
        assert opened and len({r.t for r in opened}) == len(opened), ("I4", where, opened)
        assert med.doses_per_day == len(opened), ("I4", where, med.doses_per_day, len(opened))


def _request(rnd, med_id, op, opened):
    """(method, path, body) cho thao tác, hoặc None khi thao tác không áp dụng được."""
    base = f"/medications/{med_id}"
    if op in ("edit_time", "toggle", "remove") and not opened:
        return None
    if op == "edit_time":
        return (
            "patch",
            f"{base}/schedules/{rnd.choice(opened).id}",
            {"intake_time": rnd.choice(TIMES)},
        )
    if op == "toggle":
        return (
            "patch",
            f"{base}/schedules/{rnd.choice(opened).id}",
            {"reminder_enabled": rnd.choice([True, False])},
        )
    if op == "remove":
        return "delete", f"{base}/schedules/{rnd.choice(opened).id}", None
    if op == "add":
        return "post", f"{base}/schedules", {"intake_time": rnd.choice(TIMES)}
    bodies = {
        "days": lambda: {"days_of_week": sorted(rnd.sample(range(1, 8), rnd.randint(1, 7)))},
        "stop": lambda: {"stopped": True},
        "unstop": lambda: {"stopped": False},
        "as_needed": lambda: {"dosing_mode": "as_needed", "max_doses_per_day": 2},
        "scheduled": lambda: {
            "dosing_mode": "scheduled",
            "intake_times": sorted(rnd.sample(TIMES, 2)),
        },
        "times": lambda: {"intake_times": sorted(rnd.sample(TIMES, rnd.randint(1, 3)))},
    }
    return "patch", base, bodies[op]()


@pytest.mark.parametrize("seed", SEEDS)
def test_random_sequences_keep_invariants__AC30(client, db, make, auth, scheduled_body, seed):
    rnd = random.Random(seed)
    h = auth(make.user())
    med_id = client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=h
    ).json()["id"]
    trail = []
    for step in range(10):
        _, rows, _ = _state(db, med_id)
        opened = [r for r in rows if r.ended_at is None]
        op = rnd.choice(OPS)
        if op == "early":
            if not opened:
                continue
            s = rnd.choice(opened)
            # Liều sớm (tối đa 30 phút trước giờ, QD-01) nằm trong khoảng của lịch: xác nhận
            # liều (2.10) chưa tự kiểm khoảng hiệu lực, nên test chỉ ghi liều hợp lệ.
            at = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=rnd.randint(1, 25))
            at = max(at, s.effective_from.replace(microsecond=0) + timedelta(seconds=1))
            exists = db.execute(
                text(
                    "SELECT 1 FROM dose_logs "
                    "WHERE medication_schedule_id = :s AND scheduled_at = :a"
                ),
                {"s": s.id, "a": at},
            ).first()
            if not exists:
                make.dose_log(s.id, at, status="da_uong")
            trail.append(("early", s.id))
            _check(db, med_id, (seed, step, trail))
            continue
        req = _request(rnd, med_id, op, opened)
        if req is None:
            continue
        method, path, body = req
        r = client.request(method, path, json=body, headers=h)
        trail.append((op, body, r.status_code))
        assert r.status_code < 500, ("I5", seed, step, r.text, trail)
        _check(db, med_id, (seed, step, trail))
