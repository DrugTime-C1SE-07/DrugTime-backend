"""GET /family/link-code (task 3.10, QD-04): mỗi user đúng một mã cố định, không hết hạn.

Test có hậu tố AC32 thuộc task 3.13 (BS-05); các AC khác theo đánh số của 3.10.
"""

import logging
import re
import threading
import time
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text

from drugtime.modules.family.domain.link_code import generate_code

URL = "/family/link-code"
CODE_RE = re.compile(r"^[A-HJKMNP-Z2-9]{10}$")
# Task 3.13 (BS-05): phải đồng ý family_sharing mới lấy được mã.
SHARING = ("family_sharing",)


@pytest.fixture
def tx(admin_engine):
    """Kết nối có transaction thật (không autocommit) để giữ khóa."""
    conn = admin_engine.execution_options(isolation_level="READ COMMITTED").connect()
    yield conn
    conn.close()


def _rows(db, user_id):
    rows = db.execute(
        text("SELECT code, created_at FROM link_codes WHERE patient_user_id = :u"), {"u": user_id}
    )
    return [dict(r._mapping) for r in rows]


def _total(db):
    return db.execute(text("SELECT count(*) FROM link_codes")).scalar_one()


def _wait_until_blocked(db, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waiting = db.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE usename = 'api_role' AND wait_event_type = 'Lock'"
            )
        ).scalar_one()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("request never waited on the lock")


def _in_thread(fn):
    result = {}

    def run():
        result["response"] = fn()

    t = threading.Thread(target=run)
    t.start()
    return t, result


def test_first_call_creates_one_row__AC1(client, db, make, auth):
    user = make.user(consents=SHARING)

    r = client.get(URL, headers=auth(user))

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"code", "qr_payload"}
    assert CODE_RE.match(body["code"])
    assert [row["code"] for row in _rows(db, user)] == [body["code"]]


def test_repeated_calls_return_same_code__AC2(client, db, make, auth):
    user = make.user(consents=SHARING)
    first = client.get(URL, headers=auth(user)).json()
    created_at = _rows(db, user)[0]["created_at"]

    for _ in range(3):
        r = client.get(URL, headers=auth(user))
        assert r.status_code == 200
        assert r.json() == first

    assert _rows(db, user) == [{"code": first["code"], "created_at": created_at}]


def test_waits_for_concurrent_insert_and_returns_its_code__AC3(client, tx, db, make, auth):
    """Request khác (giả lập bằng kết nối tx) đang tạo mã cho U, chưa commit: API chờ ở
    ON CONFLICT rồi trả đúng mã của bên kia, không tạo dòng thứ hai, không 5xx."""
    user = make.user(consents=SHARING)
    winner = generate_code()
    tx.begin()
    tx.execute(
        text("INSERT INTO link_codes (patient_user_id, code) VALUES (:u, :c)"),
        {"u": user, "c": winner},
    )

    t, result = _in_thread(lambda: client.get(URL, headers=auth(user)))
    _wait_until_blocked(db)
    tx.commit()
    t.join(timeout=15)

    r = result["response"]
    assert r.status_code == 200, r.text
    assert r.json()["code"] == winner
    assert [row["code"] for row in _rows(db, user)] == [winner]


def test_parallel_first_calls_same_code__AC3(client, db, make, auth):
    user = make.user(consents=SHARING)
    barrier = threading.Barrier(2)

    def send():
        barrier.wait()
        return client.get(URL, headers=auth(user))

    threads = [_in_thread(send) for _ in range(2)]
    for t, _ in threads:
        t.join(timeout=15)
    responses = [res["response"] for _, res in threads]

    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert len(_rows(db, user)) == 1


def test_qr_payload_contains_code__AC5(client, make, auth):
    body = client.get(URL, headers=auth(make.user(consents=SHARING))).json()
    url = urlparse(body["qr_payload"])

    assert body["qr_payload"] == f"drugtime://link?code={body['code']}"
    assert (url.scheme, url.netloc) == ("drugtime", "link")
    assert parse_qs(url.query) == {"code": [body["code"]]}


def test_codes_are_per_user_and_query_ignored__AC6(client, db, make, auth):
    u, v = make.user(consents=SHARING), make.user(consents=SHARING)

    code_u = client.get(URL, headers=auth(u)).json()["code"]
    r = client.get(URL, params={"patient_user_id": str(v), "user_id": str(v)}, headers=auth(u))

    assert r.status_code == 200
    assert r.json()["code"] == code_u
    assert _rows(db, v) == []
    code_v = client.get(URL, headers=auth(v)).json()["code"]
    assert code_v != code_u
    assert [row["code"] for row in _rows(db, u)] == [code_u]
    assert [row["code"] for row in _rows(db, v)] == [code_v]


@pytest.mark.parametrize("case", ["no_header", "bad_token", "erased_account"])
def test_unauthenticated_401_no_row__AC8(client, db, make, auth, case):
    user = make.user(consents=())
    headers = {
        "no_header": {},
        "bad_token": {"Authorization": "Bearer not-a-valid-token"},
        "erased_account": auth(user),
    }[case]
    if case == "erased_account":
        db.execute(
            text(
                "UPDATE users SET erased_at = now(), email = NULL, full_name = NULL WHERE id = :u"
            ),
            {"u": user},
        )
    before = _total(db)

    r = client.get(URL, headers=headers)

    assert r.status_code == 401
    assert _total(db) == before
    assert _rows(db, user) == []


def test_admin_403_khong_co_quyen_no_row__AC9(client, db, admin_auth):
    admin_id, headers = admin_auth
    before = _total(db)

    r = client.get(URL, headers=headers)

    assert r.status_code == 403
    assert r.json() == {"detail": "khong_co_quyen"}
    assert _total(db) == before
    assert _rows(db, admin_id) == []


def test_code_not_logged__AC10(client, make, auth, caplog):
    """Log của ứng dụng (logger drugtime ở mức DEBUG, các logger khác ở mức mặc định)."""
    caplog.set_level(logging.DEBUG, logger="drugtime")
    user = make.user(consents=SHARING)

    body = client.get(URL, headers=auth(user)).json()
    client.get(URL, headers=auth(user))

    assert body["code"] not in caplog.text
    assert body["qr_payload"] not in caplog.text


def test_unknown_user_token_401(client, auth):
    """Token hợp lệ của user không tồn tại: 401, không lộ gì (bổ sung cho AC8)."""
    assert client.get(URL, headers=auth(uuid4())).status_code == 401


@pytest.mark.parametrize("history", ["never", "withdrawn"])
def test_without_family_sharing_403__AC32(client, db, make, auth, history):
    """Chưa từng đồng ý (chỉ có health_data), hoặc đã rút: 403, không sinh mã."""
    user = make.user()
    if history == "withdrawn":
        make.consent(user, "family_sharing")
        make.revoke_consent(user, "family_sharing")
    before = _total(db)

    r = client.get(URL, headers=auth(user))

    assert r.status_code == 403
    assert r.json() == {"detail": "family_sharing_consent_required"}
    assert _total(db) == before
    assert _rows(db, user) == []


def test_after_consent_returns_same_code__AC32(client, db, make, auth):
    """Đồng ý qua POST /consents thì lấy được mã; rút rồi đồng ý lại thì vẫn là mã cũ (QD-04)."""
    user = make.user()
    consent = {"purpose": "family_sharing", "document_version": "2026-10-v1"}
    assert client.post("/consents", json=consent, headers=auth(user)).status_code == 201
    first = client.get(URL, headers=auth(user))
    assert first.status_code == 200, first.text

    withdraw = client.post("/consents/family_sharing/withdraw", headers=auth(user))
    assert withdraw.status_code == 200, withdraw.text
    assert client.get(URL, headers=auth(user)).status_code == 403
    assert client.post("/consents", json=consent, headers=auth(user)).status_code == 201
    again = client.get(URL, headers=auth(user))

    assert again.status_code == 200
    assert again.json() == first.json()
    assert [row["code"] for row in _rows(db, user)] == [first.json()["code"]]
