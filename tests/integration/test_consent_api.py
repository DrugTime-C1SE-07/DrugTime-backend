"""Test tích hợp /consents (task 1.14) với Postgres thật, app chạy bằng api_role.

Consent trong các test này luôn được cấp/rút qua API thật, không chèn bằng factory.consent:
lỗ hổng "người dùng mới không có đường tạo consent" từng lọt vì fixture chèn thẳng vào DB.
"""

import threading
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text

# Thứ tự khai báo của Purpose = thứ tự GET /consents trả (contract). terms: task
# adhoc-20261003-login-medication-ui-fixes.
PURPOSES = ["health_data", "family_sharing", "ai_meal", "terms"]
VERSION = "2026-10-v1"
OLD_VERSION = "2026-09-v0"


def _rows(db, user_id: UUID) -> list[dict]:
    """Mọi dòng user_consents của một người dùng, theo thứ tự ghi."""
    rows = db.execute(
        text(
            "SELECT id, consent_type::text AS purpose, status::text AS status, consented_at, "
            "revoked_at, document_version FROM user_consents WHERE user_id = :u ORDER BY id"
        ),
        {"u": user_id},
    )
    return [dict(r._mapping) for r in rows]


def _grant(client, auth, user_id, purpose, version=VERSION):
    return client.post(
        "/consents",
        json={"purpose": purpose, "document_version": version},
        headers=auth(user_id),
    )


def _withdraw(client, auth, user_id, purpose):
    return client.post(f"/consents/{purpose}/withdraw", headers=auth(user_id))


def _status(client, auth, user_id) -> dict[str, str]:
    r = client.get("/consents", headers=auth(user_id))
    assert r.status_code == 200, r.text
    return {c["purpose"]: c["status"] for c in r.json()["items"]}


def _create_medication(client, auth, user_id, make, scheduled_body):
    return client.post(
        "/medications", json=scheduled_body(make.catalog_medication()), headers=auth(user_id)
    )


# ------------------------------------------------------------------ AC1


def test_new_user_lists_four_not_granted__AC1_AC31(client, db, make, auth):
    user = make.user(consents=())

    r = client.get("/consents", headers=auth(user))

    assert r.status_code == 200
    assert r.json() == {
        "items": [
            {
                "purpose": p,
                "status": "not_granted",
                "granted_at": None,
                "document_version": None,
                "current_document_version": VERSION,
            }
            for p in PURPOSES
        ]
    }
    assert _rows(db, user) == []


# ------------------------------------------------------------------ AC2, AC3


def test_grant_health_data_creates_one_row__AC2(client, db, make, auth):
    user = make.user(consents=())
    before = datetime.now(UTC)

    r = _grant(client, auth, user, "health_data")

    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["purpose"], body["status"]) == ("health_data", "granted")
    assert (body["document_version"], body["current_document_version"]) == (VERSION, VERSION)
    # Thời điểm theo múi giờ Asia/Ho_Chi_Minh, như các thời điểm khác của API.
    assert body["granted_at"].endswith("+07:00")
    granted_at = datetime.fromisoformat(body["granted_at"])
    assert granted_at >= before.replace(microsecond=0)

    [row] = _rows(db, user)
    assert (row["purpose"], row["status"], row["document_version"]) == (
        "health_data",
        "dong_y",
        VERSION,
    )
    assert row["revoked_at"] is None
    assert row["consented_at"] == granted_at
    assert _status(client, auth, user) == {
        "health_data": "granted",
        "family_sharing": "not_granted",
        "ai_meal": "not_granted",
        "terms": "not_granted",
    }


def test_new_user_medications_403_until_granted_then_201__AC3(client, make, auth, scheduled_body):
    user = make.user(consents=())

    denied = _create_medication(client, auth, user, make, scheduled_body)
    assert (denied.status_code, denied.json()) == (403, {"detail": "consent_revoked"})

    assert _grant(client, auth, user, "health_data").status_code == 201
    created = _create_medication(client, auth, user, make, scheduled_body)

    assert created.status_code == 201, created.text
    assert client.get("/medications", headers=auth(user)).status_code == 200


# ------------------------------------------------------------------ AC4


def test_regrant_returns_200_without_new_row__AC4(client, db, make, auth):
    user = make.user(consents=())
    first = _grant(client, auth, user, "health_data")

    again = _grant(client, auth, user, "health_data")

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()  # granted_at của lần đầu giữ nguyên
    assert len(_rows(db, user)) == 1


def test_concurrent_grants_create_one_active_row__AC4(client, db, make, auth):
    user = make.user(consents=())
    barrier = threading.Barrier(2)
    responses = []

    def send():
        barrier.wait()
        responses.append(_grant(client, auth, user, "health_data"))

    threads = [threading.Thread(target=send) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert sorted(r.status_code for r in responses) == [200, 201]
    assert responses[0].json()["granted_at"] == responses[1].json()["granted_at"]
    rows = _rows(db, user)
    assert [(r["purpose"], r["status"]) for r in rows] == [("health_data", "dong_y")]


# ------------------------------------------------------------------ AC5 (QA: rút consent)


def test_withdraw_health_data_then_medications_403__AC5(client, db, make, auth, scheduled_body):
    user = make.user(consents=())
    _grant(client, auth, user, "health_data")
    med = _create_medication(client, auth, user, make, scheduled_body).json()

    r = _withdraw(client, auth, user, "health_data")

    assert r.status_code == 200, r.text
    assert r.json() == {
        "purpose": "health_data",
        "status": "not_granted",
        "granted_at": None,
        "document_version": None,
        "current_document_version": VERSION,
    }
    [row] = _rows(db, user)  # không xóa dòng, chỉ đánh dấu
    assert row["status"] == "thu_hoi"
    assert row["revoked_at"] is not None and row["revoked_at"] >= row["consented_at"]

    # Request kế tiếp, ngay sau khi rút: bị từ chối ở mọi endpoint thuốc của chính chủ.
    for method, path in (("get", "/medications"), ("get", f"/medications/{med['id']}")):
        denied = client.request(method, path, headers=auth(user))
        assert (denied.status_code, denied.json()) == (403, {"detail": "consent_revoked"}), path
    denied = _create_medication(client, auth, user, make, scheduled_body)
    assert denied.status_code == 403


# ------------------------------------------------------------------ AC6 (QA: truy cập chéo)


def test_withdraw_family_sharing_keeps_health_data_and_blocks_family__AC6(
    client, make, auth, scheduled_body
):
    patient = make.user(consents=())
    _grant(client, auth, patient, "health_data")
    _grant(client, auth, patient, "family_sharing")
    family = make.user(consents=())
    make.link(patient, family, sharing=True)
    med = _create_medication(client, auth, patient, make, scheduled_body).json()

    # Cặp được phép: trước khi rút, người thân xem được và có dòng allowed.
    allowed = client.get(f"/medications/{med['id']}", headers=auth(family))
    assert allowed.status_code == 200, allowed.text
    assert make.access_logs(patient)[-1]["result"] == "allowed"

    assert _withdraw(client, auth, patient, "family_sharing").status_code == 200

    # Mục đích khác không bị ảnh hưởng.
    assert _status(client, auth, patient)["health_data"] == "granted"
    assert client.get("/medications", headers=auth(patient)).status_code == 200
    # Người thân: request kế tiếp bị từ chối và có dòng denied.
    denied = client.get(f"/medications/{med['id']}", headers=auth(family))
    assert (denied.status_code, denied.json()) == (403, {"detail": "khong_co_quyen"})
    last = make.access_logs(patient)[-1]
    assert (last["actor_user_id"], last["result"]) == (family, "denied")


def test_withdraw_health_data_also_blocks_family__AC6(client, make, auth, scheduled_body):
    """Rút health_data: người thân cũng mất quyền (cần cả health_data lẫn family_sharing)."""
    patient = make.user(consents=())
    _grant(client, auth, patient, "health_data")
    _grant(client, auth, patient, "family_sharing")
    family = make.user(consents=())
    make.link(patient, family, sharing=True)
    med = _create_medication(client, auth, patient, make, scheduled_body).json()

    _withdraw(client, auth, patient, "health_data")

    denied = client.get(f"/medications/{med['id']}", headers=auth(family))
    assert denied.status_code == 403
    assert make.access_logs(patient)[-1]["result"] == "denied"
    assert _status(client, auth, patient)["family_sharing"] == "granted"


# ------------------------------------------------------------------ AC7


def test_regrant_after_withdraw_adds_new_row__AC7(client, db, make, auth):
    user = make.user(consents=())
    _grant(client, auth, user, "health_data")
    _withdraw(client, auth, user, "health_data")
    assert client.get("/medications", headers=auth(user)).status_code == 403

    r = _grant(client, auth, user, "health_data")

    assert r.status_code == 201
    assert [(row["status"], row["revoked_at"] is None) for row in _rows(db, user)] == [
        ("thu_hoi", False),
        ("dong_y", True),
    ]
    assert client.get("/medications", headers=auth(user)).status_code == 200


# ------------------------------------------------------------------ AC8


def test_withdraw_without_active_is_idempotent__AC8(client, db, make, auth):
    user = make.user(consents=())
    _grant(client, auth, user, "health_data")
    before = _rows(db, user)

    never = _withdraw(client, auth, user, "ai_meal")  # chưa từng đồng ý
    _withdraw(client, auth, user, "family_sharing")
    twice = _withdraw(client, auth, user, "family_sharing")  # rút lại

    assert (never.status_code, never.json()["status"]) == (200, "not_granted")
    assert (twice.status_code, twice.json()["status"]) == (200, "not_granted")
    assert _rows(db, user) == before


def test_withdraw_twice_keeps_first_revoked_at__AC8(client, db, make, auth):
    user = make.user(consents=())
    _grant(client, auth, user, "ai_meal")
    _withdraw(client, auth, user, "ai_meal")
    [first] = _rows(db, user)

    assert _withdraw(client, auth, user, "ai_meal").status_code == 200

    assert _rows(db, user) == [first]


# ------------------------------------------------------------------ AC9


def test_outdated_version_422_writes_nothing__AC9(client, db, make, auth):
    user = make.user(consents=())

    for version in ("2026-09-v0", "2026-10-V1", "x" * 64):
        r = _grant(client, auth, user, "health_data", version=version)
        assert (r.status_code, r.json()) == (422, {"detail": "consent_document_outdated"})

    for body in (
        {"purpose": "all", "document_version": VERSION},
        {"purpose": ["health_data", "ai_meal"], "document_version": VERSION},
        {"purpose": "health_data", "document_version": VERSION, "user_id": str(user)},
        {"purpose": "health_data", "document_version": ""},
    ):
        r = client.post("/consents", json=body, headers=auth(user))
        assert r.status_code == 422, body
        assert isinstance(r.json()["detail"], list), body

    r = client.post("/consents/everything/withdraw", headers=auth(user))
    assert r.status_code == 422
    assert _rows(db, user) == []


# ------------------------------------------------------------------ AC10


def test_requires_auth__AC10(client):
    for method, path, body in (
        ("get", "/consents", None),
        ("post", "/consents", {"purpose": "health_data", "document_version": VERSION}),
        ("post", "/consents/health_data/withdraw", None),
    ):
        r = client.request(method, path, json=body)
        assert r.status_code == 401, path
    r = client.get("/consents", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_only_touches_caller__AC10(client, db, make, auth):
    a = make.user(consents=())
    b = make.user(consents=())
    _grant(client, auth, b, "ai_meal")
    b_before = _rows(db, b)

    _grant(client, auth, a, "health_data")
    _grant(client, auth, a, "ai_meal")
    _withdraw(client, auth, a, "ai_meal")

    assert _rows(db, b) == b_before
    assert _status(client, auth, b) == {
        "health_data": "not_granted",
        "family_sharing": "not_granted",
        "ai_meal": "granted",
        "terms": "not_granted",
    }
    assert {r["purpose"] for r in _rows(db, a)} == {"health_data", "ai_meal"}


def test_admin_web_session_sees_own_consents(client, make):
    """Contract: mọi phiên hợp lệ, kể cả admin_web, chỉ thấy consent của chính mình."""
    from drugtime.modules.identity.application.sign_in import issue_app_session
    from drugtime.modules.identity.domain.user import SessionType

    admin = make.user(admin=True, consents=())
    token = issue_app_session(admin, SessionType.ADMIN_WEB, datetime.now(UTC)).token

    r = client.get("/consents", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    assert [c["status"] for c in r.json()["items"]] == ["not_granted"] * len(PURPOSES)


# ------------------------------------------------------------------ M1 (review vòng 1, chạy đua)


def test_withdraw_in_transaction_started_before_concurrent_grant__M1(client, db, make, auth):
    """Rút trong transaction mở TRƯỚC khi một lần cấp song song commit.

    Request rút mở transaction từ câu đọc users của current_user (cùng UoW), rồi mới UPDATE.
    Nếu một lần cấp commit xen giữa, UPDATE thấy dòng mới có consented_at muộn hơn now() của
    transaction rút. Dùng now() thì vi phạm CHECK revoked_at >= consented_at → 500.
    Qua HTTP không điều khiển được khe hở này một cách tất định, nên transaction rút được giữ
    bằng adapter thật trên kết nối api_role của app; lần cấp đi qua API."""
    from drugtime.modules.consent.adapters.outbound.sql_consent import SqlConsents
    from drugtime.modules.consent.domain.purpose import Purpose
    from drugtime.shared.db import SqlUnitOfWork, get_engine

    user = make.user(consents=())
    _grant(client, auth, user, "health_data")
    _withdraw(client, auth, user, "health_data")

    with get_engine().connect() as conn:
        tx = conn.begin()
        started = conn.execute(text("SELECT now()")).scalar_one()  # transaction rút bắt đầu

        regrant = _grant(client, auth, user, "health_data")  # request khác, commit ngay
        assert regrant.status_code == 201, regrant.text
        assert datetime.fromisoformat(regrant.json()["granted_at"]) > started

        SqlConsents().withdraw_active(SqlUnitOfWork(conn), user, Purpose.HEALTH_DATA)
        tx.commit()

    rows = _rows(db, user)
    assert [r["status"] for r in rows] == ["thu_hoi", "thu_hoi"]
    assert all(r["revoked_at"] >= r["consented_at"] for r in rows)
    assert _status(client, auth, user)["health_data"] == "not_granted"


# ================================================================== terms
# Đồng ý Điều khoản dịch vụ và Chính sách quyền riêng tư (task
# adhoc-20261003-login-medication-ui-fixes, AC24–AC31 của task đó).


def _seed_terms(db, user_id: UUID, version: str = OLD_VERSION) -> None:
    """Dòng terms đang hiệu lực ở phiên bản cho trước, như người dùng đã đồng ý bản cũ.

    Chèn thẳng vì API chỉ nhận phiên bản hiện hành; consented_at lùi một ngày cho rõ thứ tự."""
    db.execute(
        text(
            "INSERT INTO user_consents (user_id, consent_type, document_version, consented_at) "
            "VALUES (:u, 'terms', :v, now() - interval '1 day')"
        ),
        {"u": user_id, "v": version},
    )


def _terms_rows(db, user_id: UUID) -> list[dict]:
    return [r for r in _rows(db, user_id) if r["purpose"] == "terms"]


def _race(send, n: int = 2) -> list:
    """Chạy n request cùng lúc (sau một barrier), trả các response."""
    barrier = threading.Barrier(n)
    responses = []

    def run():
        barrier.wait()
        responses.append(send())

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    return responses


def test_terms_listed_last_with_current_version__AC31(client, make, auth):
    user = make.user(consents=())

    items = client.get("/consents", headers=auth(user)).json()["items"]

    assert [i["purpose"] for i in items] == PURPOSES
    assert items[-1] == {
        "purpose": "terms",
        "status": "not_granted",
        "granted_at": None,
        "document_version": None,
        "current_document_version": "2026-10-v1",
    }


def test_grant_terms_201_then_200_one_row__AC25(client, db, make, auth):
    user = make.user(consents=())

    first = _grant(client, auth, user, "terms")
    again = _grant(client, auth, user, "terms")

    assert (first.status_code, again.status_code) == (201, 200), first.text
    assert first.json()["purpose"] == "terms"
    assert (first.json()["status"], first.json()["document_version"]) == ("granted", VERSION)
    assert again.json() == first.json()  # tick lại không tạo dòng mới, granted_at giữ nguyên
    [row] = _rows(db, user)
    assert (row["purpose"], row["status"], row["document_version"]) == ("terms", "dong_y", VERSION)
    assert _status(client, auth, user)["terms"] == "granted"


def test_grant_terms_replaces_outdated_version__AC26(client, db, make, auth):
    user = make.user(consents=())
    _seed_terms(db, user)
    [old] = _terms_rows(db, user)
    listed = client.get("/consents", headers=auth(user)).json()["items"][-1]
    assert (listed["document_version"], listed["current_document_version"]) == (
        OLD_VERSION,
        VERSION,
    )

    r = _grant(client, auth, user, "terms")

    assert r.status_code == 201, r.text
    assert (r.json()["document_version"], r.json()["status"]) == (VERSION, "granted")
    revoked, active = _terms_rows(db, user)
    assert (revoked["id"], revoked["status"], revoked["document_version"]) == (
        old["id"],
        "thu_hoi",
        OLD_VERSION,
    )
    assert revoked["revoked_at"] is not None
    assert revoked["revoked_at"] >= revoked["consented_at"]
    assert (active["status"], active["document_version"], active["revoked_at"]) == (
        "dong_y",
        VERSION,
        None,
    )
    assert datetime.fromisoformat(r.json()["granted_at"]) == active["consented_at"]

    again = _grant(client, auth, user, "terms")  # đã đúng bản hiện hành: không thay nữa
    assert again.status_code == 200
    assert len(_terms_rows(db, user)) == 2


def test_outdated_health_data_is_kept_not_replaced(client, db, make, auth):
    """Thay phiên bản chỉ áp dụng cho terms; health_data giữ hành vi 1.14 (task riêng)."""
    user = make.user(consents=())
    make.consent(user, "health_data")  # document_version 'test', khác bản hiện hành

    r = _grant(client, auth, user, "health_data")

    assert r.status_code == 200
    assert r.json()["document_version"] == "test"
    assert [(row["status"], row["document_version"]) for row in _rows(db, user)] == [
        ("dong_y", "test")
    ]


def test_grant_terms_wrong_version_422_writes_nothing__AC27(client, db, make, auth):
    fresh = make.user(consents=())
    seeded = make.user(consents=())
    _seed_terms(db, seeded)
    seeded_before = _rows(db, seeded)

    for user in (fresh, seeded):
        for version in (OLD_VERSION, "2026-11-v1", "2026-10-V1"):
            r = _grant(client, auth, user, "terms", version=version)
            assert (r.status_code, r.json()) == (422, {"detail": "consent_document_outdated"})

    assert _rows(db, fresh) == []
    assert _rows(db, seeded) == seeded_before  # bản cũ không bị thu hồi


def test_withdraw_terms_422_keeps_row__AC28(client, db, make, auth):
    user = make.user(consents=())
    _grant(client, auth, user, "terms")
    before = _rows(db, user)

    r = _withdraw(client, auth, user, "terms")

    assert (r.status_code, r.json()) == (422, {"detail": "consent_not_withdrawable"})
    assert _rows(db, user) == before
    assert before[0]["status"] == "dong_y"
    assert _status(client, auth, user)["terms"] == "granted"


def test_withdraw_terms_without_active_is_also_422__AC28(client, db, make, auth):
    user = make.user(consents=())

    r = _withdraw(client, auth, user, "terms")

    assert (r.status_code, r.json()) == (422, {"detail": "consent_not_withdrawable"})
    assert _rows(db, user) == []


def test_concurrent_terms_replace_one_active_row__AC29(client, db, make, auth):
    # Lặp vài người dùng để tăng khả năng hai transaction thực sự chồng nhau.
    for _ in range(3):
        user = make.user(consents=())
        _seed_terms(db, user)

        responses = _race(lambda user=user: _grant(client, auth, user, "terms"))

        assert sorted(r.status_code for r in responses) == [200, 201], [r.text for r in responses]
        assert responses[0].json() == responses[1].json()
        rows = _terms_rows(db, user)
        assert [(r["status"], r["document_version"]) for r in rows] == [
            ("thu_hoi", OLD_VERSION),
            ("dong_y", VERSION),
        ]
        assert rows[0]["revoked_at"] >= rows[0]["consented_at"]


def test_concurrent_first_terms_grant_one_row__AC29(client, db, make, auth):
    user = make.user(consents=())

    responses = _race(lambda: _grant(client, auth, user, "terms"))

    assert sorted(r.status_code for r in responses) == [200, 201]
    assert [(r["status"], r["document_version"]) for r in _terms_rows(db, user)] == [
        ("dong_y", VERSION)
    ]


def test_terms_does_not_affect_pep__AC30(client, make, auth, scheduled_body):
    """terms không phải quyền truy cập dữ liệu: rút health_data vẫn chặn ngay ở request kế tiếp."""
    user = make.user(consents=())
    _grant(client, auth, user, "terms")
    _grant(client, auth, user, "health_data")
    med = _create_medication(client, auth, user, make, scheduled_body)
    assert med.status_code == 201, med.text

    # Thử rút terms (bị từ chối) không làm đổi quyền đọc thuốc.
    assert _withdraw(client, auth, user, "terms").status_code == 422
    assert client.get("/medications", headers=auth(user)).status_code == 200

    assert _withdraw(client, auth, user, "health_data").status_code == 200
    denied = client.get("/medications", headers=auth(user))
    assert (denied.status_code, denied.json()) == (403, {"detail": "consent_revoked"})


def test_terms_alone_does_not_open_medications__AC30(client, make, auth, scheduled_body):
    user = make.user(consents=())
    assert _grant(client, auth, user, "terms").status_code == 201

    for r in (
        client.get("/medications", headers=auth(user)),
        _create_medication(client, auth, user, make, scheduled_body),
    ):
        assert (r.status_code, r.json()) == (403, {"detail": "consent_revoked"})


def test_terms_without_health_data_family_still_denied__AC30(client, make, auth, scheduled_body):
    """Người bệnh có terms + family_sharing nhưng đã rút health_data: người thân bị từ chối,
    có dòng denied. Cặp được phép kiểm trước khi rút."""
    patient = make.user(consents=())
    for purpose in ("terms", "health_data", "family_sharing"):
        assert _grant(client, auth, patient, purpose).status_code == 201
    family = make.user(consents=())
    make.link(patient, family, sharing=True)
    med = _create_medication(client, auth, patient, make, scheduled_body).json()

    allowed = client.get(f"/medications/{med['id']}", headers=auth(family))
    assert allowed.status_code == 200, allowed.text
    assert make.access_logs(patient)[-1]["result"] == "allowed"

    _withdraw(client, auth, patient, "health_data")

    denied = client.get(f"/medications/{med['id']}", headers=auth(family))
    assert denied.status_code == 403
    last = make.access_logs(patient)[-1]
    assert (last["actor_user_id"], last["result"]) == (family, "denied")
    assert _status(client, auth, patient)["terms"] == "granted"
