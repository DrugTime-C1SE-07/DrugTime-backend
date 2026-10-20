"""POST /family/link-requests (task 3.13, PB19, QD-04, QD-34, BS-04, BS-05).

Thời gian của app được cố định bằng `frozen_clock` (thay `clock.now`); mốc trong DB
(`rejected_at`, `linked_at`, `attempted_at`) được dựng tương đối với mốc đó bằng kết nối quản trị.
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from drugtime.modules.family.domain.link_code import generate_code
from drugtime.modules.family.domain.link_request import next_vn_midnight, vn_day_start

URL = "/family/link-requests"
# 12:00 giờ VN của ngày hiện tại: xa nửa đêm, nên phép tính theo ngày không phụ thuộc giờ chạy.
NOON_VN = vn_day_start(datetime.now(UTC)) + timedelta(hours=12)


@pytest.fixture
def frozen_clock(monkeypatch):
    """frozen_clock(at): app thấy `clock.now() == at` cho tới khi gọi lại."""
    from drugtime.shared import clock

    def freeze(at: datetime) -> datetime:
        monkeypatch.setattr(clock, "now", lambda: at)
        return at

    return freeze


@pytest.fixture
def tx(admin_engine):
    """Kết nối có transaction thật để giữ advisory lock của người gửi."""
    conn = admin_engine.execution_options(isolation_level="READ COMMITTED").connect()
    yield conn
    conn.close()


@pytest.fixture
def patient_code(client, make, auth):
    """patient_code() -> (P, C): người bệnh có consent family_sharing và đã lấy mã qua API."""

    def create():
        patient = make.user(consents=("health_data", "family_sharing"))
        r = client.get("/family/link-code", headers=auth(patient))
        assert r.status_code == 200, r.text
        return patient, r.json()["code"]

    return create


def _send(client, auth, family, code, client_uuid=None):
    body = {"client_uuid": str(client_uuid or uuid4()), "code": code}
    return client.post(URL, json=body, headers=auth(family))


def _wrong_code():
    return generate_code()  # 31^10 khả năng: không trùng mã đã có trong thực tế


def _links(db, patient, family):
    rows = db.execute(
        text(
            "SELECT id, status::text AS status, sharing_enabled, client_uuid, linked_at, "
            "revoked_at, rejected_at FROM caregiver_links "
            "WHERE patient_user_id = :p AND family_user_id = :f ORDER BY id"
        ),
        {"p": patient, "f": family},
    )
    return [dict(r._mapping) for r in rows]


def _family_links(db, family):
    return db.execute(
        text("SELECT count(*) FROM caregiver_links WHERE family_user_id = :f"), {"f": family}
    ).scalar_one()


def _attempts(db, family):
    rows = db.execute(
        text(
            "SELECT client_uuid, attempted_at, account_locked_until FROM link_request_attempts "
            "WHERE family_user_id = :f ORDER BY id"
        ),
        {"f": family},
    )
    return [dict(r._mapping) for r in rows]


def _row(db, patient, family, status, *, at=None, sharing=False):
    """Chèn một dòng caregiver_links; `at` là mốc từ chối/hủy (và cũng là linked_at)."""
    at = at or datetime.now(UTC)
    return db.execute(
        text(
            "INSERT INTO caregiver_links (patient_user_id, family_user_id, status, "
            "sharing_enabled, linked_at, revoked_at, rejected_at) "
            "VALUES (:p, :f, CAST(:s AS link_status), :share, :at, "
            "CASE WHEN :s = 'revoked' THEN CAST(:at AS timestamptz) END, "
            "CASE WHEN :s = 'rejected' THEN CAST(:at AS timestamptz) END) RETURNING id"
        ),
        {"p": patient, "f": family, "s": status, "share": sharing, "at": at},
    ).scalar_one()


def _lock_out(client, auth, family, frozen_clock, at):
    """Cho `family` sai 5 lần lúc `at` (lần thứ 5 khóa tài khoản tới at + 15 phút)."""
    frozen_clock(at)
    for _ in range(5):
        assert _send(client, auth, family, _wrong_code()).status_code == 404


def _advisory_lock(tx, family):
    tx.begin()
    tx.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('family_link_request:' || CAST(:f AS text), 0))"
        ),
        {"f": family},
    )


def _run_parallel(fns):
    results = [None] * len(fns)

    def run(i, fn):
        results[i] = fn()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    return threads, results


# --- Tạo yêu cầu (AC1, AC2, AC7, AC9) -------------------------------------------------------


def test_creates_pending_without_profile__AC1(client, db, make, auth, patient_code):
    patient, code = patient_code()
    family = make.user(consents=())  # consent của người gửi không được kiểm (AC34)
    codes_before = db.execute(
        text("SELECT code, created_at FROM link_codes WHERE patient_user_id = :p"), {"p": patient}
    ).all()

    r = _send(client, auth, family, code)

    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "status", "requested_at"}
    assert body["status"] == "pending"
    assert str(patient) not in r.text and "Test User" not in r.text
    [link] = _links(db, patient, family)
    assert (link["id"], link["status"], link["sharing_enabled"]) == (body["id"], "pending", False)
    assert datetime.fromisoformat(body["requested_at"]) == link["linked_at"]
    assert (
        db.execute(
            text("SELECT code, created_at FROM link_codes WHERE patient_user_id = :p"),
            {"p": patient},
        ).all()
        == codes_before
    )
    # Mã vẫn dùng được cho người thân khác.
    other = make.user(consents=())
    assert _send(client, auth, other, code).status_code == 201
    assert _attempts(db, family) == []


def test_pending_link_grants_no_access__AC2(client, db, make, auth, patient_code):
    patient, code = patient_code()
    family = make.user()
    assert _send(client, auth, family, code).status_code == 201

    r = client.get(f"/patients/{patient}/schedules", headers=auth(family))

    assert r.status_code == 403
    assert r.json() == {"detail": "khong_co_quyen"}
    logs = make.access_logs(patient)
    assert [(log["actor_user_id"], log["result"]) for log in logs] == [(family, "denied")]


@pytest.mark.parametrize("reverse_status", ["pending", "active"])
def test_reverse_direction_201__AC7(client, db, make, auth, patient_code, reverse_status):
    """F cũng là người bệnh; P đã có yêu cầu/liên kết tới F theo chiều (F, P)."""
    patient, code = patient_code()
    family = make.user()
    _row(db, family, patient, reverse_status)

    r = _send(client, auth, family, code)

    assert r.status_code == 201, r.text
    assert [link["status"] for link in _links(db, patient, family)] == ["pending"]
    assert [link["status"] for link in _links(db, family, patient)] == [reverse_status]


def test_resend_after_revoked_sharing_false__AC9(client, db, make, auth, patient_code):
    patient, code = patient_code()
    family = make.user()
    old_id = _row(db, patient, family, "revoked", sharing=True)
    old = _links(db, patient, family)

    r = _send(client, auth, family, code)

    assert r.status_code == 201, r.text
    links = _links(db, patient, family)
    assert links[0] == old[0]
    assert (links[0]["id"], len(links)) == (old_id, 2)
    assert (links[1]["id"], links[1]["status"], links[1]["sharing_enabled"]) == (
        r.json()["id"],
        "pending",
        False,
    )


# --- Xác thực, quyền, mã không hợp lệ (AC3, AC4, AC5, AC6, AC16) -----------------------------


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-valid-token"}])
def test_unauthenticated_401__AC3(client, db, patient_code, headers):
    patient, code = patient_code()
    attempts_before = db.execute(text("SELECT count(*) FROM link_request_attempts")).scalar_one()

    r = client.post(URL, json={"client_uuid": str(uuid4()), "code": code}, headers=headers)

    assert r.status_code == 401
    assert (
        db.execute(
            text("SELECT count(*) FROM caregiver_links WHERE patient_user_id = :p"), {"p": patient}
        ).scalar_one()
        == 0
    )
    assert (
        db.execute(text("SELECT count(*) FROM link_request_attempts")).scalar_one()
        == attempts_before
    )


def test_unknown_code_404_counted__AC4(client, db, make, auth):
    family = make.user()
    key = uuid4()

    r = _send(client, auth, family, _wrong_code(), key)

    assert r.status_code == 404
    assert r.json() == {"detail": "link_code_not_found"}
    assert [a["client_uuid"] for a in _attempts(db, family)] == [key]
    assert _family_links(db, family) == 0


def test_failure_persisted_after_rollback__AC12(client, admin_engine, make, auth, frozen_clock):
    """Request trả 404 (transaction của request rollback); lượt sai vẫn đọc được từ kết nối
    khác, với đúng mốc thời gian của app."""
    family = make.user()
    at = frozen_clock(NOON_VN)
    key = uuid4()

    assert _send(client, auth, family, _wrong_code(), key).status_code == 404

    with admin_engine.connect() as other:
        rows = other.execute(
            text(
                "SELECT client_uuid, attempted_at, account_locked_until "
                "FROM link_request_attempts WHERE family_user_id = :f"
            ),
            {"f": family},
        ).all()
    assert [tuple(r) for r in rows] == [(key, at, None)]


def test_self_code_422__AC5(client, db, auth, patient_code):
    patient, code = patient_code()

    r = _send(client, auth, patient, code)

    assert r.status_code == 422
    assert r.json() == {"detail": "self_link_not_allowed"}
    assert _links(db, patient, patient) == []
    assert _attempts(db, patient) == []


@pytest.mark.parametrize(
    "existing, detail", [("pending", "link_request_pending"), ("active", "already_linked")]
)
def test_open_pair_409__AC6(client, db, make, auth, patient_code, existing, detail):
    """Cặp đang pending, hoặc active kể cả khi đã tắt chia sẻ."""
    patient, code = patient_code()
    family = make.user()
    _row(db, patient, family, existing, sharing=False)
    before = _links(db, patient, family)

    r = _send(client, auth, family, code)

    assert r.status_code == 409
    assert r.json() == {"detail": detail}
    assert _links(db, patient, family) == before
    assert _attempts(db, family) == []


def test_admin_403__AC16(client, db, admin_auth, patient_code):
    patient, code = patient_code()
    admin_id, headers = admin_auth

    r = client.post(URL, json={"client_uuid": str(uuid4()), "code": code}, headers=headers)

    assert r.status_code == 403
    assert r.json() == {"detail": "khong_co_quyen"}
    assert _family_links(db, admin_id) == 0
    assert _attempts(db, admin_id) == []


# --- Chặn sau từ chối, BS-04 (AC8, AC8b) -------------------------------------------------------


@pytest.mark.parametrize("rejections", [1, 4])
def test_rejected_1_to_4_times_can_resend__AC8(
    client, db, make, auth, patient_code, frozen_clock, rejections
):
    patient, code = patient_code()
    family = make.user()
    now = frozen_clock(NOON_VN)
    for i in range(rejections):
        _row(db, patient, family, "rejected", at=now - timedelta(minutes=10 - i))
    before = _links(db, patient, family)

    r = _send(client, auth, family, code)

    assert r.status_code == 201, r.text
    links = _links(db, patient, family)
    assert links[:rejections] == before
    assert [link["status"] for link in links[rejections:]] == ["pending"]


def test_fifth_rejection_blocks_24h__AC8b(client, db, make, auth, patient_code, frozen_clock):
    patient, code = patient_code()
    family = make.user()
    fifth = NOON_VN - timedelta(hours=23, minutes=59)
    for i in range(5):
        _row(db, patient, family, "rejected", at=fifth - timedelta(minutes=4 - i))
    before = _links(db, patient, family)

    frozen_clock(fifth + timedelta(hours=23, minutes=59))
    r = _send(client, auth, family, code)

    assert r.status_code == 429
    assert r.json() == {"detail": "link_request_cooldown"}
    assert r.headers["Retry-After"] == "60"
    assert _links(db, patient, family) == before
    assert _attempts(db, family) == []

    frozen_clock(fifth + timedelta(hours=24))
    assert _send(client, auth, family, code).status_code == 201


def test_block_expired_counter_resets__AC8b(client, db, make, auth, patient_code, frozen_clock):
    """Hết 24 giờ chặn rồi bị từ chối thêm lần nữa (lần 6): gửi lại được ngay."""
    patient, code = patient_code()
    family = make.user()
    fifth = NOON_VN - timedelta(hours=25)
    for i in range(5):
        _row(db, patient, family, "rejected", at=fifth - timedelta(minutes=4 - i))
    frozen_clock(NOON_VN - timedelta(minutes=30))
    new_id = _send(client, auth, family, code).json()["id"]
    db.execute(
        text("UPDATE caregiver_links SET status = 'rejected', rejected_at = :at WHERE id = :id"),
        {"id": new_id, "at": NOON_VN - timedelta(minutes=10)},
    )

    frozen_clock(NOON_VN)
    r = _send(client, auth, family, code)

    assert r.status_code == 201, r.text


def test_approval_resets_streak__AC8b(client, db, make, auth, patient_code, frozen_clock):
    """Từ chối 3 lần, chấp thuận (rồi bị hủy), từ chối 4 lần: chưa bị chặn."""
    patient, code = patient_code()
    family = make.user()
    now = frozen_clock(NOON_VN)
    statuses = ["rejected"] * 3 + ["revoked"] + ["rejected"] * 4
    for i, status in enumerate(statuses):
        _row(db, patient, family, status, at=now - timedelta(minutes=60 - i))

    r = _send(client, auth, family, code)

    assert r.status_code == 201, r.text


def test_other_family_unaffected__AC8b(client, db, make, auth, patient_code, frozen_clock):
    patient, code = patient_code()
    blocked, other = make.user(), make.user()
    now = frozen_clock(NOON_VN)
    for i in range(5):
        _row(db, patient, blocked, "rejected", at=now - timedelta(minutes=10 - i))

    assert _send(client, auth, blocked, code).status_code == 429
    assert _send(client, auth, other, code).status_code == 201


# --- Khóa tài khoản khi nhập sai (AC10, AC13, AC15) ---------------------------------------------


def test_fifth_failure_locks_then_unlocks__AC10(client, db, make, auth, patient_code, frozen_clock):
    patient, code = patient_code()
    family = make.user()
    start = frozen_clock(NOON_VN)
    for i in range(4):
        frozen_clock(start + timedelta(minutes=i))
        assert _send(client, auth, family, _wrong_code()).status_code == 404

    fifth = frozen_clock(start + timedelta(minutes=10))
    assert _send(client, auth, family, _wrong_code()).status_code == 404
    assert [a["account_locked_until"] for a in _attempts(db, family)] == [None] * 4 + [
        fifth + timedelta(minutes=15)
    ]

    for at, retry in [
        (fifth + timedelta(minutes=1), "840"),
        (fifth + timedelta(seconds=899.5), "1"),
    ]:
        frozen_clock(at)
        r = _send(client, auth, family, code)  # kể cả mã đúng
        assert r.status_code == 429
        assert r.json() == {"detail": "link_request_locked"}
        assert r.headers["Retry-After"] == retry
    assert _links(db, patient, family) == []
    assert len(_attempts(db, family)) == 5  # bị khóa không tính thêm lần sai

    frozen_clock(fifth + timedelta(minutes=15))
    assert _send(client, auth, family, code).status_code == 201


def test_concurrent_wrong_codes_at_most_five_404__AC13(
    client, db, tx, make, auth, frozen_clock, wait_for_lock_waiters
):
    """10 request với 10 mã sai cùng chờ khóa của người gửi rồi chạy: đúng 5 lần sai."""
    family = make.user()
    frozen_clock(NOON_VN)
    _advisory_lock(tx, family)
    codes = [_wrong_code() for _ in range(10)]
    sends = [lambda c=c: _send(client, auth, family, c) for c in codes]
    threads, results = _run_parallel(sends)
    wait_for_lock_waiters(10)
    tx.commit()
    for t in threads:
        t.join(timeout=30)

    statuses = sorted(r.status_code for r in results)
    assert statuses == [404] * 5 + [429] * 5
    assert {r.json()["detail"] for r in results if r.status_code == 429} == {"link_request_locked"}
    assert len(_attempts(db, family)) == 5


def test_burst_beyond_pool_no_500__AC13(
    client, db, tx, make, auth, frozen_clock, wait_for_lock_waiters
):
    """Hồi quy H1 (review 3.13): số request nhập sai đồng thời vượt sức chứa pool chính. Các
    request đợi khóa người gửi chiếm hết pool; người giữ khóa vẫn phải ghi được lượt sai (pool
    riêng), không 500, và request của người khác không bị treo."""
    from drugtime.shared.db import get_engine

    pool = get_engine().pool
    capacity = pool.size() + pool._max_overflow  # mặc định 5 + 10
    family = make.user()
    other = make.user(consents=("family_sharing",))
    frozen_clock(NOON_VN)
    _advisory_lock(tx, family)
    codes = [_wrong_code() for _ in range(capacity + 5)]
    threads, results = _run_parallel([lambda c=c: _send(client, auth, family, c) for c in codes])
    wait_for_lock_waiters(capacity)  # pool chính đã hết kết nối
    tx.commit()
    started = time.monotonic()
    bystander = client.get("/family/link-code", headers=auth(other))
    bystander_seconds = time.monotonic() - started
    for t in threads:
        t.join(timeout=120)

    assert bystander.status_code == 200, bystander.text
    assert bystander_seconds < 10
    assert sorted(r.status_code for r in results) == [404] * 5 + [429] * capacity
    assert len(_attempts(db, family)) == 5


def test_locked_family_does_not_block_patient_code__AC15(
    client, db, make, auth, patient_code, frozen_clock
):
    patient, code = patient_code()
    locked, other = make.user(), make.user()
    _lock_out(client, auth, locked, frozen_clock, NOON_VN)
    assert _send(client, auth, locked, code).status_code == 429

    r = _send(client, auth, other, code)

    assert r.status_code == 201, r.text
    assert [link["status"] for link in _links(db, patient, other)] == ["pending"]


# --- Giới hạn 10 yêu cầu/ngày (AC14) -----------------------------------------------------------


def test_daily_limit__AC14(client, db, make, auth, patient_code, frozen_clock):
    family = make.user()
    now = frozen_clock(NOON_VN)
    for i in range(9):
        _row(db, make.user(), family, "pending", at=now - timedelta(hours=1, minutes=i))
    _row(db, make.user(), family, "pending", at=vn_day_start(now) - timedelta(seconds=1))
    # Yêu cầu không thành công không tính vào giới hạn.
    pending_patient, pending_code = patient_code()
    _row(db, pending_patient, family, "pending", at=vn_day_start(now) - timedelta(days=2))
    assert _send(client, auth, family, pending_code).status_code == 409
    assert _send(client, auth, family, _wrong_code()).status_code == 404

    tenth_patient, tenth_code = patient_code()
    assert _send(client, auth, family, tenth_code).status_code == 201

    eleventh_patient, eleventh_code = patient_code()
    r = _send(client, auth, family, eleventh_code)
    assert r.status_code == 429
    assert r.json() == {"detail": "link_request_daily_limit"}
    assert r.headers["Retry-After"] == str(int((next_vn_midnight(now) - now).total_seconds()))
    assert _links(db, eleventh_patient, family) == []

    frozen_clock(next_vn_midnight(now))
    assert _send(client, auth, family, eleventh_code).status_code == 201


# --- Không log mã (AC17) ------------------------------------------------------------------------


def test_code_not_logged__AC17(client, db, make, auth, patient_code, frozen_clock, caplog):
    caplog.set_level(logging.DEBUG, logger="drugtime")
    patient, code = patient_code()
    family = make.user()
    frozen_clock(NOON_VN)
    wrong = [_wrong_code() for _ in range(5)]

    sent = [
        (_send(client, auth, family, code), 201),
        (_send(client, auth, family, code), 409),
        (_send(client, auth, patient, code), 422),
    ] + [(_send(client, auth, family, w), 404) for w in wrong]
    sent.append((_send(client, auth, family, code), 429))

    assert [r.status_code for r, _ in sent] == [status for _, status in sent]
    for secret in [code, code.lower(), *wrong]:
        assert secret not in caplog.text


# --- Kiểm tra body (AC20) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"client_uuid": "UUID"},
        {"client_uuid": "UUID", "code": 1234567890},
        {"client_uuid": "UUID", "code": "K7M2Q9XARO"},
        {"client_uuid": "UUID", "code": "K7M2Q9XARI"},
        {"client_uuid": "UUID", "code": "K7M2Q9XARL"},
        {"client_uuid": "UUID", "code": "K7M2Q9XAR0"},
        {"client_uuid": "UUID", "code": "K7M2Q9XAR1"},
        {"client_uuid": "UUID", "code": "K7M2Q9XAR"},
        {"client_uuid": "UUID", "code": "K7M2Q9XAR44"},
        {"code": "K7M2Q9XAR4"},
        {"client_uuid": "not-a-uuid", "code": "K7M2Q9XAR4"},
        {"client_uuid": "UUID", "code": "K7M2Q9XAR4", "patient_user_id": "x"},
    ],
    ids=[
        "thieu-code",
        "code-khong-phai-chuoi",
        "co-O",
        "co-I",
        "co-L",
        "co-0",
        "co-1",
        "9-ky-tu",
        "11-ky-tu",
        "thieu-client-uuid",
        "client-uuid-sai",
        "field-la",
    ],
)
def test_validation_422_not_counted__AC20(client, db, make, auth, body):
    family = make.user()
    body = {k: (str(uuid4()) if v == "UUID" else v) for k, v in body.items()}

    r = client.post(URL, json=body, headers=auth(family))

    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)
    assert _attempts(db, family) == []
    assert _family_links(db, family) == 0


def test_code_normalized__AC20(client, db, make, auth, patient_code):
    patient, code = patient_code()
    family = make.user()

    r = _send(client, auth, family, f"  {code.lower()} ")

    assert r.status_code == 201, r.text
    assert len(_links(db, patient, family)) == 1


# --- Gửi lại cùng client_uuid (AC29, AC30, AC31) ------------------------------------------------


def test_replay_200_current_status__AC29(client, db, make, auth, patient_code):
    patient, code = patient_code()
    family = make.user()
    key = uuid4()
    first = _send(client, auth, family, code, key)
    assert first.status_code == 201

    again = _send(client, auth, family, code, key)
    assert again.status_code == 200
    assert again.json() == first.json()

    db.execute(
        text("UPDATE caregiver_links SET status = 'active', sharing_enabled = true WHERE id = :i"),
        {"i": first.json()["id"]},
    )
    later = _send(client, auth, family, code, key)
    assert later.status_code == 200
    assert later.json() == first.json() | {"status": "active"}
    assert len(_links(db, patient, family)) == 1


@pytest.mark.parametrize("blocked_by", ["link_request_locked", "link_request_daily_limit"])
def test_replay_200_while_locked_or_daily_limit__AC29(
    client, db, make, auth, patient_code, frozen_clock, blocked_by
):
    patient, code = patient_code()
    family = make.user()
    now = frozen_clock(NOON_VN)
    key = uuid4()
    first = _send(client, auth, family, code, key)
    assert first.status_code == 201
    if blocked_by == "link_request_locked":
        _lock_out(client, auth, family, frozen_clock, now)
    else:
        for _ in range(9):
            _row(db, make.user(), family, "pending", at=now)
    _, other_code = patient_code()
    links_before = _family_links(db, family)
    blocked = _send(client, auth, family, other_code)
    assert (blocked.status_code, blocked.json()) == (429, {"detail": blocked_by})

    r = _send(client, auth, family, code, key)

    assert r.status_code == 200
    assert r.json() == first.json()
    assert _family_links(db, family) == links_before


def test_replay_ignores_other_code__AC30(client, db, make, auth, patient_code):
    patient, code = patient_code()
    other_patient, other_code = patient_code()
    family = make.user()
    key = uuid4()
    first = _send(client, auth, family, code, key).json()

    r = _send(client, auth, family, other_code, key)

    assert r.status_code == 200
    assert r.json() == first
    assert _links(db, other_patient, family) == []


def test_replay_isolated_per_user__AC30(client, db, make, auth, patient_code):
    patient, code = patient_code()
    f1, f2 = make.user(), make.user()
    key = uuid4()

    r1 = _send(client, auth, f1, code, key)
    r2 = _send(client, auth, f2, code, key)

    assert (r1.status_code, r2.status_code) == (201, 201)
    assert r1.json()["id"] != r2.json()["id"]
    assert [link["client_uuid"] for link in _links(db, patient, f2)] == [key]


def test_replay_failed_not_double_counted__AC31(client, db, make, auth):
    family = make.user()
    key, wrong = uuid4(), _wrong_code()

    assert _send(client, auth, family, wrong, key).status_code == 404
    r = _send(client, auth, family, wrong, key)

    assert r.status_code == 404
    assert [a["client_uuid"] for a in _attempts(db, family)] == [key]


def test_concurrent_same_client_uuid_201_and_200__AC31(
    client, db, tx, make, auth, patient_code, wait_for_lock_waiters
):
    patient, code = patient_code()
    family = make.user()
    key = uuid4()
    _advisory_lock(tx, family)
    threads, results = _run_parallel([lambda: _send(client, auth, family, code, key)] * 2)
    wait_for_lock_waiters(2)
    tx.commit()
    for t in threads:
        t.join(timeout=30)

    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json() == results[1].json()
    assert len(_links(db, patient, family)) == 1


# --- Consent family_sharing của chủ mã, BS-05 (AC33, AC34) --------------------------------------


def test_owner_revoked_consent_404__AC33(client, db, make, auth, patient_code):
    patient, code = patient_code()
    family = make.user()
    unknown = _send(client, auth, family, _wrong_code())
    make.revoke_consent(patient, "family_sharing")

    r = _send(client, auth, family, code)

    assert r.status_code == unknown.status_code == 404
    assert r.content == unknown.content
    assert r.headers.get("content-type") == unknown.headers.get("content-type")
    assert len(_attempts(db, family)) == 2
    assert _links(db, patient, family) == []

    make.consent(patient, "family_sharing")
    assert _send(client, auth, family, code).status_code == 201


def test_consent_revoked_takes_effect_next_request__AC34(client, db, make, auth, patient_code):
    """P rút consent qua API ngay trước request của F: request kế tiếp đã thấy."""
    patient, code = patient_code()
    f1, f2 = make.user(consents=()), make.user(consents=())
    assert _send(client, auth, f1, code).status_code == 201

    withdraw = client.post("/consents/family_sharing/withdraw", headers=auth(patient))
    assert withdraw.status_code == 200, withdraw.text
    r = _send(client, auth, f2, code)

    assert r.status_code == 404
    assert r.json() == {"detail": "link_code_not_found"}
    assert _links(db, patient, f2) == []
