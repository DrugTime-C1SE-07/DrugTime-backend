"""Đăng nhập Mobile App của user (không gồm admin) với Supabase Auth LOCAL thật — ma trận đầu vào.

Bổ sung cho `test_auth_flow.py` (task adhoc-20261007-user-login-tests, AC1–AC13): user cũ đăng nhập
lại, các dạng số điện thoại/email/OTP, sai kiểu JSON, SQL injection và chuỗi độc hại, hồ sơ ở giá
trị biên, bearer giả mạo/hết hạn. Kiểm cả phản hồi HTTP (hộp đen) lẫn dữ liệu trong DB (hộp trắng).

Cần `supabase start` (từ backend/) với `supabase/config.toml` của repo. Không gửi mail thật: mã OTP
email lấy qua Admin API `generate_link`; số điện thoại chỉ dùng số `test_otp` 84900000001 = 123456.

Giới hạn `token_verifications` của GoTrue local (30 lần / 5 phút / IP) đếm chung cho mọi test: mọi
lời gọi `/auth/mobile/verify` có tới Supabase đi qua `_verify()`, tự chờ khi vượt ngân sách
`TEST_GOTRUE_VERIFY_BUDGET` (mặc định 18) trong cửa sổ 300 giây.
"""

import os
import re
import time
from collections import deque
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import jwt
import pytest
from sqlalchemy import text
from tests.integration.test_auth_flow import (
    _LOCAL_HOSTS,
    ADMIN_PASSWORD,
    TEST_PHONE,
    TEST_PHONE_OTP,
    _bearer,
    _service_headers,
    _supabase_status,
)

VN = ZoneInfo("Asia/Ho_Chi_Minh")
TEST_PHONE_DB = "+84900000001"
TEST_PHONE_AUTH = "84900000001"  # GoTrue lưu số không có dấu "+"
_PROFILE = {"ho_ten": "Người Thử Đăng Nhập", "ngay_sinh": "1960-05-20", "gioi_tinh": "nam"}
# Dấu hiệu lộ chi tiết nội bộ trong phản hồi (Supabase, SQL, stack trace).
_LEAK_MARKERS = (
    "Traceback",
    "psycopg",
    "sqlalchemy",
    "syntax error",
    "ProgrammingError",
    "DataError",
    "error_code",
    "otp_expired",
    "refresh_token",
)
INJECTIONS = [
    "' OR '1'='1",
    "admin'--",
    "'); DROP TABLE users;--",
    "1; SELECT pg_sleep(5)--",
    "<script>alert(1)</script>",
    "${7*7}",
    "abc\u0000def",
]
INJECTION_IDS = ["or-1-1", "comment", "drop-table", "pg-sleep", "script", "template", "nul"]


# --- Hạ tầng -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def local_supabase(app_settings):
    """Trỏ app vào Supabase Auth local (giống fixture `supabase` của test_auth_flow.py)."""
    from drugtime.shared.config import get_settings

    status = _supabase_status()
    url = status.get("API_URL", "")
    if urlsplit(url).hostname not in _LOCAL_HOSTS:
        pytest.exit("Auth integration tests only run against local Supabase", returncode=2)
    env = {
        "SUPABASE_URL": url,
        "SUPABASE_ANON_KEY": status["ANON_KEY"],
        "SUPABASE_SERVICE_KEY": status["SERVICE_ROLE_KEY"],
    }
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    get_settings.cache_clear()
    yield env
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def gotrue(local_supabase):
    with httpx.Client(base_url=f"{local_supabase['SUPABASE_URL']}/auth/v1", timeout=20) as c:
        yield c


@pytest.fixture
def api(local_supabase):
    """TestClient không ném lỗi server ra test, để khẳng định được "không 5xx"."""
    from fastapi.testclient import TestClient

    from drugtime.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


class _VerifyBudget:
    """Giữ số lời gọi verify tới GoTrue trong một cửa sổ trượt dưới ngân sách."""

    window_s = 300.0

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.calls: deque[float] = deque()

    def wait_turn(self) -> None:
        now = time.monotonic()
        while self.calls and now - self.calls[0] >= self.window_s:
            self.calls.popleft()
        if len(self.calls) >= self.budget:
            time.sleep(self.window_s - (now - self.calls[0]) + 1)
            self.calls.popleft()
        self.calls.append(time.monotonic())


_BUDGET = _VerifyBudget(int(os.environ.get("TEST_GOTRUE_VERIFY_BUDGET", "18")))


def _verify(api, body: dict) -> httpx.Response:
    """POST /auth/mobile/verify cho request sẽ tới GoTrue (đếm vào ngân sách)."""
    _BUDGET.wait_turn()
    r = api.post("/auth/mobile/verify", json=body)
    if r.status_code == 429:
        pytest.fail(
            "Giới hạn token_verifications của Supabase local (lỗi môi trường, không phải lỗi sản "
            "phẩm): chờ 5 phút rồi chạy lại, hoặc giảm TEST_GOTRUE_VERIFY_BUDGET."
        )
    return r


def _email_otp(local_supabase, gotrue, email: str) -> str:
    r = gotrue.post(
        "/admin/generate_link",
        headers=_service_headers(local_supabase),
        json={"type": "magiclink", "email": email},
    )
    assert r.status_code == 200, r.status_code
    return r.json()["email_otp"]


def _new_email_account(local_supabase, gotrue, *, email: str | None = None) -> str:
    """Tài khoản Supabase Auth mới (chưa có dòng `users`), không gửi mail."""
    email = email or f"it-login-{uuid4().hex[:12]}@example.com"
    r = gotrue.post(
        "/admin/users",
        headers=_service_headers(local_supabase),
        json={"email": email, "email_confirm": True},
    )
    assert r.status_code == 200, r.status_code
    return email


@pytest.fixture
def email_account(local_supabase, gotrue) -> str:
    return _new_email_account(local_supabase, gotrue)


@pytest.fixture
def phone_account(api, db) -> None:
    """Bảo đảm GoTrue đã có user của số `test_otp` (verify tìm user theo số trước khi so mã)."""
    exists = db.execute(
        text("SELECT count(*) FROM auth.users WHERE phone = :p"), {"p": TEST_PHONE_AUTH}
    ).scalar_one()
    if not exists:
        r = api.post("/auth/mobile/otp", json={"phone": TEST_PHONE})
        assert r.status_code == 204, r.status_code


@pytest.fixture
def fresh_user(db) -> UUID:
    """Dòng `users` mới chưa có hồ sơ (full_name NULL), cho test chỉ cần phiên app."""
    uid = uuid4()
    db.execute(
        text("INSERT INTO users (id, email) VALUES (:i, :e)"),
        {"i": uid, "e": f"{uid}@test.local"},
    )
    return uid


def _profile_row(db, user_id) -> dict:
    row = db.execute(
        text(
            "SELECT full_name, date_of_birth, gender, system_role::text AS system_role "
            "FROM users WHERE id = :i"
        ),
        {"i": user_id},
    ).one()
    return dict(row._mapping)


def _users_with_email(db, email: str) -> int:
    return db.execute(
        text("SELECT count(*) FROM users WHERE lower(email) = lower(:e)"), {"e": email}
    ).scalar_one()


def _auth_user_count(db) -> int:
    return db.execute(text("SELECT count(*) FROM auth.users")).scalar_one()


_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}(\.[A-Za-z0-9_-]*){0,2}")


def _body(r: httpx.Response) -> str:
    """Thân phản hồi đã che token (pytest in giá trị trong assert khi fail; token không vào log)."""
    return _JWT.sub("***", r.text)


def _short(r: httpx.Response) -> str:
    return _body(r)[:200]


def _assert_no_5xx_no_leak(r: httpx.Response) -> None:
    assert r.status_code < 500, (r.status_code, _short(r))
    for marker in _LEAK_MARKERS:
        assert marker not in _body(r), (marker, _short(r))


# --- AC1–AC4: luồng tài khoản ------------------------------------------------------------------


def test_returning_email_user_same_id_profile_complete__AC1(
    api, local_supabase, gotrue, db, email_account, auth
):
    first = _verify(
        api, {"email": email_account, "token": _email_otp(local_supabase, gotrue, email_account)}
    )
    assert first.status_code == 200, _short(first)
    assert first.json()["profile_complete"] is False
    user_id = first.json()["user_id"]
    token = first.json()["session"]["access_token"]
    assert api.post("/auth/profile", headers=_bearer(token), json=_PROFILE).status_code == 204

    second = _verify(
        api, {"email": email_account, "token": _email_otp(local_supabase, gotrue, email_account)}
    )

    assert second.status_code == 200, _short(second)
    body = second.json()
    assert body["user_id"] == user_id
    assert body["profile_complete"] is True
    assert body["session"]["session_type"] == "mobile"
    assert abs(body["session"]["expires_in"] - 10 * 24 * 3600) <= 60
    assert "supabase" not in body
    assert "refresh_token" not in _body(second)
    assert _users_with_email(db, email_account) == 1


def test_local_phone_format_logs_in_and_wrong_otp_401__AC2(api, db, phone_account):
    ok = _verify(api, {"phone": TEST_PHONE, "token": TEST_PHONE_OTP})
    assert ok.status_code == 200, _short(ok)
    stored = db.execute(
        text("SELECT phone_number FROM users WHERE id = :i"), {"i": ok.json()["user_id"]}
    ).scalar_one()
    assert stored == TEST_PHONE_DB

    wrong = _verify(api, {"phone": TEST_PHONE, "token": "000000"})

    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "Invalid credentials"}
    _assert_no_5xx_no_leak(wrong)


def test_admin_account_on_mobile_forbidden__AC3(api, local_supabase, gotrue):
    import importlib.util

    from tests.integration.test_auth_flow import BACKEND_DIR

    spec = importlib.util.spec_from_file_location(
        "create_dev_admin", BACKEND_DIR / "scripts" / "create_dev_admin.py"
    )
    admin_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(admin_script)
    email = f"it-login-admin-{uuid4().hex[:12]}@example.com"
    admin_script.ensure_admin(
        email,
        ADMIN_PASSWORD,
        supabase_url=local_supabase["SUPABASE_URL"],
        service_key=local_supabase["SUPABASE_SERVICE_KEY"],
        db_url=os.environ.get(
            "TEST_ADMIN_DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres",
        ),
    )

    r = _verify(api, {"email": email, "token": _email_otp(local_supabase, gotrue, email)})

    assert r.status_code == 403
    assert r.json() == {"detail": "admin_must_use_web"}
    assert "session" not in _body(r)


def test_erased_user_session_and_relogin_rejected__AC4(
    api, local_supabase, gotrue, db, email_account
):
    first = _verify(
        api, {"email": email_account, "token": _email_otp(local_supabase, gotrue, email_account)}
    )
    assert first.status_code == 200, _short(first)
    user_id, token = first.json()["user_id"], first.json()["session"]["access_token"]
    # Cùng câu với SqlUsers.erase(): ràng buộc CHECK đòi xóa mọi trường định danh.
    db.execute(
        text(
            "UPDATE users SET full_name = NULL, date_of_birth = NULL, gender = NULL, "
            "email = NULL, phone_number = NULL, erased_at = now() WHERE id = :i"
        ),
        {"i": user_id},
    )

    profile = api.post("/auth/profile", headers=_bearer(token), json=_PROFILE)
    relogin = _verify(
        api, {"email": email_account, "token": _email_otp(local_supabase, gotrue, email_account)}
    )

    assert profile.status_code == 401
    assert relogin.status_code == 401
    assert "session" not in _body(relogin)


# --- AC5–AC7: số điện thoại ----------------------------------------------------------------------

VALID_PHONE_FORMATS = [
    "0900000001",
    "+84900000001",
    "+84 900 000 001",
    "0900-000-001",
    "  0900000001  ",
]


def test_phone_formats_same_user__AC5(api, db, phone_account):
    ids = {}
    for raw in VALID_PHONE_FORMATS:
        r = _verify(api, {"phone": raw, "token": TEST_PHONE_OTP})
        assert r.status_code == 200, (raw, r.status_code, _short(r))
        ids[raw] = r.json()["user_id"]

    assert len(set(ids.values())) == 1, ids
    rows = db.execute(
        text("SELECT id::text, phone_number FROM users WHERE phone_number = :p"),
        {"p": TEST_PHONE_DB},
    ).all()
    assert [(r.id, r.phone_number) for r in rows] == [(next(iter(ids.values())), TEST_PHONE_DB)]


INVALID_PHONES = [
    "84900000001",
    "(+84)900000001",
    "09abc12345",
    "+84 900 000 001",
    "0900000001\n",
    "+8490000",
    "+8490000000000000",
    "+",
    "0",
]


@pytest.mark.parametrize("endpoint", ["/auth/mobile/otp", "/auth/mobile/verify"])
@pytest.mark.parametrize("phone", INVALID_PHONES)
def test_invalid_phone_rejected_before_provider__AC6(api, db, endpoint, phone):
    before = _auth_user_count(db)
    body = {"phone": phone, "token": "123456"} if endpoint.endswith("verify") else {"phone": phone}

    r = api.post(endpoint, json=body)

    assert (r.status_code, r.json()) == (422, {"detail": "invalid_phone"}), (phone, _short(r))
    assert _auth_user_count(db) == before


@pytest.mark.parametrize("phone", ["+84900000", "+849000000000000"], ids=["9-ky-tu", "16-ky-tu"])
def test_phone_length_boundaries_accepted_by_backend__AC6(api, phone):
    otp = api.post("/auth/mobile/otp", json={"phone": phone})
    verify = _verify(api, {"phone": phone, "token": "123456"})

    for r in (otp, verify):
        assert "invalid_phone" not in _body(r), _short(r)
        assert r.status_code < 500 or r.status_code == 503, (r.status_code, _short(r))
        for marker in _LEAK_MARKERS:
            assert marker not in _body(r), (marker, _short(r))


@pytest.mark.parametrize("endpoint", ["/auth/mobile/otp", "/auth/mobile/verify"])
@pytest.mark.parametrize(
    "phone", ["+８４９０００００００１", "+٨٤٩٠٠٠٠٠٠٠١"], ids=["fullwidth", "arabic-indic"]
)
def test_unicode_digit_phone_rejected__AC7(api, db, endpoint, phone):
    before = _auth_user_count(db)
    body = {"phone": phone, "token": "123456"} if endpoint.endswith("verify") else {"phone": phone}

    r = _verify(api, body) if endpoint.endswith("verify") else api.post(endpoint, json=body)

    assert (r.status_code, r.json() if r.content else None) == (422, {"detail": "invalid_phone"}), (
        r.status_code,
        _short(r),
    )
    assert _auth_user_count(db) == before


# --- AC8–AC9: email và OTP -----------------------------------------------------------------------


def test_email_case_and_spaces_same_user__AC8(api, local_supabase, gotrue, db):
    tag = uuid4().hex[:10]
    lower = f"user.test+{tag}@example.com"
    _new_email_account(local_supabase, gotrue, email=lower)

    mixed = _verify(
        api,
        {
            "email": f"User.Test+{tag}@Example.COM",
            "token": _email_otp(local_supabase, gotrue, lower),
        },
    )
    padded = _verify(
        api, {"email": f"  {lower}  ", "token": _email_otp(local_supabase, gotrue, lower)}
    )

    assert mixed.status_code == 200, _short(mixed)
    assert padded.status_code == 200, _short(padded)
    assert mixed.json()["user_id"] == padded.json()["user_id"]
    stored = db.execute(
        text("SELECT email FROM users WHERE id = :i"), {"i": mixed.json()["user_id"]}
    ).scalar_one()
    assert stored == lower


@pytest.mark.parametrize("endpoint", ["/auth/mobile/otp", "/auth/mobile/verify"])
@pytest.mark.parametrize(
    ("email", "detail"),
    [
        ("abc", "invalid_email"),
        ("a@b", "invalid_email"),
        ("a@@b.com", "invalid_email"),
        ("a b@c.com", "invalid_email"),
        ("@example.com", "invalid_email"),
        ("a@example.", "invalid_email"),
        ("", "login_identifier_required"),
        ("   ", "login_identifier_required"),
    ],
)
def test_invalid_email_rejected__AC8(api, endpoint, email, detail):
    body = {"email": email, "token": "123456"} if endpoint.endswith("verify") else {"email": email}

    r = api.post(endpoint, json=body)

    assert (r.status_code, r.json()) == (422, {"detail": detail}), _short(r)


@pytest.mark.parametrize(
    "email",
    [f"{'a' * 300}@example.com", "nguyễn@example.com"],
    ids=["320-ky-tu", "unicode"],
)
def test_long_and_unicode_email_no_5xx__AC8(api, email):
    r = api.post("/auth/mobile/otp", json={"email": email})

    assert r.status_code < 500 or r.status_code == 503, (r.status_code, _short(r))
    for marker in _LEAK_MARKERS:
        assert marker not in _body(r), (marker, _short(r))


def test_empty_token_422__AC9(api, email_account):
    r = api.post("/auth/mobile/verify", json={"email": email_account, "token": ""})

    assert r.status_code == 422


def test_blank_token_401_no_user__AC9(api, db, email_account):
    r = api.post("/auth/mobile/verify", json={"email": email_account, "token": "   "})

    assert r.status_code == 401
    assert _users_with_email(db, email_account) == 0


@pytest.mark.parametrize(
    "token", ["12345", "1234567", "abcdef", "1" * 1000], ids=["5", "7", "chu", "1000"]
)
def test_malformed_tokens_no_5xx__AC9(api, db, email_account, token):
    r = _verify(api, {"email": email_account, "token": token})

    assert r.status_code in (401, 422), (r.status_code, _short(r))
    _assert_no_5xx_no_leak(r)
    assert _users_with_email(db, email_account) == 0


# --- AC10: sai kiểu JSON, body hỏng, field thừa --------------------------------------------------

WRONG_TYPES = [900000001, ["0900000001"], {"v": "0900000001"}, True]
WRONG_TYPE_IDS = ["so", "mang", "object", "bool"]


@pytest.mark.parametrize("value", WRONG_TYPES, ids=WRONG_TYPE_IDS)
@pytest.mark.parametrize(
    ("endpoint", "field"),
    [
        ("/auth/mobile/otp", "phone"),
        ("/auth/mobile/otp", "email"),
        ("/auth/mobile/verify", "token"),
        ("/auth/profile", "ho_ten"),
        ("/auth/profile", "gioi_tinh"),
    ],
)
def test_wrong_json_types_no_5xx__AC10(api, auth, fresh_user, endpoint, field, value):
    base = {
        "/auth/mobile/otp": {},
        "/auth/mobile/verify": {"email": f"{uuid4().hex}@example.com"},
        "/auth/profile": dict(_PROFILE),
    }[endpoint]
    headers = auth(fresh_user) if endpoint == "/auth/profile" else {}

    r = api.post(endpoint, json={**base, field: value}, headers=headers)

    assert 400 <= r.status_code < 500, (r.status_code, _short(r))
    _assert_no_5xx_no_leak(r)


@pytest.mark.parametrize("endpoint", ["/auth/mobile/otp", "/auth/mobile/verify", "/auth/profile"])
@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        ("{not json", "application/json"),
        ("", "application/json"),
        ("phone=0900000001", "text/plain"),
    ],
    ids=["json-hong", "rong", "text-plain"],
)
def test_malformed_body_no_5xx__AC10(api, auth, fresh_user, endpoint, content, content_type):
    headers = {"Content-Type": content_type}
    if endpoint == "/auth/profile":
        headers.update(auth(fresh_user))

    r = api.post(endpoint, content=content, headers=headers)

    assert 400 <= r.status_code < 500, (r.status_code, _short(r))
    _assert_no_5xx_no_leak(r)


def test_extra_fields_have_no_effect__AC10(
    api, local_supabase, gotrue, db, email_account, auth, fresh_user
):
    other = fresh_user
    verify = _verify(
        api,
        {
            "email": email_account,
            "token": _email_otp(local_supabase, gotrue, email_account),
            "system_role": "admin",
            "user_id": str(other),
        },
    )
    assert verify.status_code == 200, _short(verify)
    me = verify.json()["user_id"]
    token = verify.json()["session"]["access_token"]

    profile = api.post(
        "/auth/profile",
        headers=_bearer(token),
        json={**_PROFILE, "user_id": str(other), "system_role": "admin"},
    )

    assert me != str(other)
    assert profile.status_code == 204, _short(profile)
    assert _profile_row(db, me)["system_role"] == "user"
    assert _profile_row(db, me)["full_name"] == _PROFILE["ho_ten"]
    assert _profile_row(db, other)["full_name"] is None


# --- AC11: SQL injection và chuỗi độc hại --------------------------------------------------------


def _timed_post(api, path: str, **kwargs) -> tuple[httpx.Response, float]:
    started = time.monotonic()
    r = api.post(path, **kwargs)
    return r, time.monotonic() - started


@pytest.mark.parametrize("payload", INJECTIONS, ids=INJECTION_IDS)
@pytest.mark.parametrize("field", ["phone", "email"])
def test_injection_in_identifier_rejected_no_leak__AC11(api, db, field, payload):
    r, elapsed = _timed_post(api, "/auth/mobile/otp", json={field: payload})

    assert r.status_code == 422, (r.status_code, _short(r))
    _assert_no_5xx_no_leak(r)
    assert elapsed < 3
    assert db.execute(text("SELECT to_regclass('public.users') IS NOT NULL")).scalar_one()


@pytest.mark.parametrize("payload", INJECTIONS, ids=INJECTION_IDS)
def test_injection_in_token_no_5xx_no_leak__AC11(api, db, email_account, payload):
    started = time.monotonic()
    r = _verify(api, {"email": email_account, "token": payload})
    elapsed = time.monotonic() - started

    _assert_no_5xx_no_leak(r)
    assert r.status_code in (401, 422), (r.status_code, _short(r))
    assert elapsed < 3 or "pg_sleep" not in payload
    assert _users_with_email(db, email_account) == 0


@pytest.mark.parametrize("payload", INJECTIONS, ids=INJECTION_IDS)
def test_injection_in_full_name_stored_verbatim__AC11(api, db, auth, fresh_user, payload):
    r, elapsed = _timed_post(
        api, "/auth/profile", headers=auth(fresh_user), json={**_PROFILE, "ho_ten": payload}
    )

    _assert_no_5xx_no_leak(r)
    assert elapsed < 3
    assert r.status_code == 204, (r.status_code, _short(r))
    assert _profile_row(db, fresh_user)["full_name"] == payload
    assert db.execute(text("SELECT to_regclass('public.users') IS NOT NULL")).scalar_one()


@pytest.mark.parametrize("payload", INJECTIONS, ids=INJECTION_IDS)
def test_injection_in_gender_rejected__AC11(api, db, auth, fresh_user, payload):
    r = api.post("/auth/profile", headers=auth(fresh_user), json={**_PROFILE, "gioi_tinh": payload})

    _assert_no_5xx_no_leak(r)
    assert (r.status_code, r.json()) == (422, {"detail": "invalid_gender"})
    assert _profile_row(db, fresh_user)["full_name"] is None


def test_injection_group_leaves_users_table_intact__AC11(api, db, auth, fresh_user):
    before = db.execute(text("SELECT count(*) FROM users")).scalar_one()
    for payload in INJECTIONS:
        api.post("/auth/mobile/otp", json={"phone": payload})
        api.post("/auth/mobile/otp", json={"email": payload})
        api.post("/auth/profile", headers=auth(fresh_user), json={**_PROFILE, "gioi_tinh": payload})

    assert db.execute(text("SELECT to_regclass('public.users') IS NOT NULL")).scalar_one()
    assert db.execute(text("SELECT count(*) FROM users")).scalar_one() == before


# --- AC12: hồ sơ ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"ho_ten": "Nguyễn Văn Ấn"}, {"full_name": "Nguyễn Văn Ấn"}),
        ({"ho_ten": "Bà Lan 👵🏻💊"}, {"full_name": "Bà Lan 👵🏻💊"}),
        ({"gioi_tinh": "NAM"}, {"gender": "nam"}),
        ({"ho_ten": "A" * 255}, {"full_name": "A" * 255}),
        ({"ngay_sinh": "1900-01-01"}, {"date_of_birth": date(1900, 1, 1)}),
    ],
    ids=["tieng-viet", "emoji", "gioi-tinh-hoa", "ten-255", "ngay-1900-01-01"],
)
def test_profile_valid_classes_saved__AC12(api, db, auth, fresh_user, override, expected):
    r = api.post("/auth/profile", headers=auth(fresh_user), json={**_PROFILE, **override})

    assert r.status_code == 204, _short(r)
    row = _profile_row(db, fresh_user)
    for column, value in expected.items():
        assert row[column] == value


@pytest.mark.parametrize(
    ("override", "detail"),
    [
        ({"ho_ten": ""}, "invalid_full_name"),
        ({"ho_ten": "   "}, "invalid_full_name"),
        ({"gioi_tinh": "x"}, "invalid_gender"),
        ({"gioi_tinh": ""}, "invalid_gender"),
        ({"ngay_sinh": "2026-02-30"}, None),
        ({"ngay_sinh": "30/01/1990"}, None),
        ({"ngay_sinh": "abc"}, None),
    ],
    ids=[
        "ten-rong",
        "ten-khoang-trang",
        "gioi-tinh-x",
        "gioi-tinh-rong",
        "30-02",
        "dd-mm-yyyy",
        "abc",
    ],
)
def test_profile_invalid_classes_422_db_unchanged__AC12(
    api, db, auth, fresh_user, override, detail
):
    r = api.post("/auth/profile", headers=auth(fresh_user), json={**_PROFILE, **override})

    assert r.status_code == 422, _short(r)
    if detail:
        assert r.json() == {"detail": detail}
    assert _profile_row(db, fresh_user)["full_name"] is None  # profile_complete vẫn false


@pytest.mark.parametrize(
    "override",
    [{"ho_ten": "A" * 256}, {"ngay_sinh": "1899-12-31"}, {"ngay_sinh": "0001-01-01"}],
    ids=["ten-256", "ngay-1899-12-31", "ngay-0001-01-01"],
)
def test_profile_limits_255_and_1900__AC12(api, db, auth, fresh_user, override):
    """Q4 của 01-requirement: họ tên tối đa 255 ký tự, ngày sinh từ 1900-01-01."""
    r = api.post("/auth/profile", headers=auth(fresh_user), json={**_PROFILE, **override})

    assert r.status_code == 422, (r.status_code, _short(r))
    assert _profile_row(db, fresh_user)["full_name"] is None


@pytest.fixture
def frozen_clock(monkeypatch):
    """Cố định `now()` mà /auth/profile dùng (adapters/inbound/http.py)."""
    from drugtime.modules.identity.adapters.inbound import http as identity_http

    def freeze(at: datetime) -> None:
        monkeypatch.setattr(identity_http, "now", lambda: at)

    return freeze


@pytest.mark.parametrize(
    "vn_time",
    [datetime(2026, 10, 8, 0, 30, tzinfo=VN), datetime(2026, 10, 8, 12, 0, tzinfo=VN)],
    ids=["0h30-gio-VN", "12h-gio-VN"],
)
def test_birth_date_today_in_vietnam_accepted__AC12(
    api, db, auth, fresh_user, frozen_clock, vn_time
):
    """Bất biến 7: "hôm nay" tính theo Asia/Ho_Chi_Minh, kể cả 00:00–07:00 (UTC vẫn là hôm qua)."""
    frozen_clock(vn_time.astimezone(UTC))

    r = api.post(
        "/auth/profile",
        headers=auth(fresh_user),
        json={**_PROFILE, "ngay_sinh": vn_time.date().isoformat()},
    )

    assert r.status_code == 204, (r.status_code, _short(r))


def test_birth_date_tomorrow_in_vietnam_rejected__AC12(api, db, auth, fresh_user, frozen_clock):
    vn_time = datetime(2026, 10, 8, 12, 0, tzinfo=VN)
    frozen_clock(vn_time.astimezone(UTC))

    r = api.post(
        "/auth/profile",
        headers=auth(fresh_user),
        json={**_PROFILE, "ngay_sinh": (vn_time.date() + timedelta(days=1)).isoformat()},
    )

    assert (r.status_code, r.json()) == (422, {"detail": "invalid_date_of_birth"})
    assert _profile_row(db, fresh_user)["full_name"] is None


# --- AC13: bearer --------------------------------------------------------------------------------


def _bad_bearers(user_id: UUID) -> dict[str, dict[str, str]]:
    from drugtime.modules.identity.application.sign_in import issue_app_session
    from drugtime.modules.identity.domain.user import SessionType

    good = issue_app_session(user_id, SessionType.MOBILE, datetime.now(UTC)).token
    head, payload, signature = good.split(".")
    tampered = (
        f"{head}.{payload}.{signature[:-2]}{'A' if signature[-2] != 'A' else 'B'}{signature[-1]}"
    )
    expired = issue_app_session(
        user_id, SessionType.MOBILE, datetime.now(UTC) - timedelta(days=11)
    ).token
    claims = jwt.decode(good, options={"verify_signature": False})
    other_secret = jwt.encode(claims, "other-secret-" + "x" * 32, algorithm="HS256")
    return {
        "khong-header": {},
        "basic": {"Authorization": f"Basic {good}"},
        "bearer-rong": {"Authorization": "Bearer "},
        "bearer-injection": {"Authorization": "Bearer ' OR '1'='1"},
        "sua-chu-ky": _bearer(tampered),
        "het-han": _bearer(expired),
        "secret-khac": _bearer(other_secret),
    }


@pytest.mark.parametrize(
    "case",
    [
        "khong-header",
        "basic",
        "bearer-rong",
        "bearer-injection",
        "sua-chu-ky",
        "het-han",
        "secret-khac",
    ],
)
def test_bad_bearer_401_db_unchanged__AC13(api, db, fresh_user, case):
    headers = _bad_bearers(fresh_user)[case]

    r = api.post("/auth/profile", headers=headers, json=_PROFILE)

    assert r.status_code == 401, (r.status_code, _short(r))
    assert _profile_row(db, fresh_user)["full_name"] is None
