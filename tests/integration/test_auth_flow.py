"""Luồng đăng nhập /auth/* với Supabase Auth LOCAL thật (GoTrue + Mailpit + Postgres).

Cần `supabase start` (từ backend/) với `supabase/config.toml` của repo: mẫu email OTP có
`{{ .Token }}`, SMS `test_otp` 84900000001 = 123456. Địa chỉ và key lấy từ `supabase status`,
luôn là localhost; không bao giờ chạy với Supabase hosted.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[2]
MAILPIT = os.environ.get("TEST_MAILPIT_URL", "http://127.0.0.1:54324")
TEST_PHONE = "0900000001"  # [auth.sms.test_otp] 84900000001 = "123456"
TEST_PHONE_OTP = "123456"
ADMIN_PASSWORD = "IntegrationAdmin#2026"
_LOCAL_HOSTS = {"127.0.0.1", "localhost"}
_PROFILE = {"ho_ten": "Người Thử Tích Hợp", "ngay_sinh": "1958-04-12", "gioi_tinh": "nu"}


def _supabase_status() -> dict[str, str]:
    cli = shutil.which("supabase")
    cmd = [cli] if cli else [shutil.which("npx") or "npx", "--no-install", "supabase"]
    try:
        out = subprocess.run(
            [*cmd, "status", "-o", "env"],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"Cannot read `supabase status` ({exc}); run `supabase start`")
    pairs = (line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {k.strip(): v.strip().strip('"') for k, v in pairs}


@pytest.fixture(scope="module")
def supabase(app_settings):
    """Trỏ app vào Supabase Auth local; trả về địa chỉ và key cho test gọi thẳng GoTrue."""
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
def gotrue(supabase):
    return httpx.Client(base_url=f"{supabase['SUPABASE_URL']}/auth/v1", timeout=20)


def _service_headers(supabase) -> dict[str, str]:
    key = supabase["SUPABASE_SERVICE_KEY"]
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _new_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}@example.com"


def _mail_otp(email: str, timeout_s: float = 15.0) -> str:
    """Mã 6 số trong email gửi tới `email`; Mailpit nhận thư bất đồng bộ nên phải hỏi lại."""
    deadline = time.monotonic() + timeout_s
    with httpx.Client(base_url=MAILPIT, timeout=5) as mailpit:
        while time.monotonic() < deadline:
            found = mailpit.get("/api/v1/search", params={"query": f"to:{email}"}).json()
            for message in found["messages"]:
                body = mailpit.get(f"/api/v1/message/{message['ID']}").json()
                code = re.search(r"\b(\d{6})\b", body.get("Text", ""))
                if code:
                    return code.group(1)
            time.sleep(0.2)
    raise AssertionError(f"No OTP email for {email} in Mailpit after {timeout_s}s")


def _generated_email_otp(supabase, gotrue, email: str) -> str:
    """Mã OTP mới cho user đã có, lấy qua Admin API (không gửi mail, không bị giới hạn tần suất)."""
    r = gotrue.post(
        "/admin/generate_link",
        headers=_service_headers(supabase),
        json={"type": "magiclink", "email": email},
    )
    assert r.status_code == 200, r.text
    return r.json()["email_otp"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _auth_user_count(db, email: str) -> int:
    return db.execute(
        text("SELECT count(*) FROM auth.users WHERE lower(email) = :e"), {"e": email}
    ).scalar_one()


@pytest.fixture(scope="module")
def admin_script():
    spec = importlib.util.spec_from_file_location(
        "create_dev_admin", BACKEND_DIR / "scripts" / "create_dev_admin.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dev_admin(supabase, admin_script) -> tuple[str, UUID]:
    """Admin mới tạo bằng hàm của scripts/create_dev_admin.py (AC7)."""
    email = _new_email("it-admin")
    user_id = admin_script.ensure_admin(
        email,
        ADMIN_PASSWORD,
        supabase_url=supabase["SUPABASE_URL"],
        service_key=supabase["SUPABASE_SERVICE_KEY"],
        db_url=os.environ.get(
            "TEST_ADMIN_DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres",
        ),
    )
    return email, user_id


@pytest.fixture
def password_user(supabase, gotrue, db) -> tuple[str, str, UUID]:
    """User thường có mật khẩu trên Supabase Auth và dòng `users` (system_role mặc định)."""
    email, password = _new_email("it-plain"), "PlainUser#2026"
    r = gotrue.post(
        "/admin/users",
        headers=_service_headers(supabase),
        json={"email": email, "password": password, "email_confirm": True},
    )
    assert r.status_code == 200, r.text
    user_id = UUID(r.json()["id"])
    db.execute(text("INSERT INTO users (id, email) VALUES (:i, :e)"), {"i": user_id, "e": email})
    return email, password, user_id


# --- Mobile: email OTP -------------------------------------------------------------------------


def test_email_otp_new_user_then_complete_profile__AC5_AC3a(client, supabase, gotrue, db):
    email = _new_email("it-mobile")

    r = client.post("/auth/mobile/otp", json={"email": email})
    assert r.status_code == 204, r.text
    code = _mail_otp(email)

    r = client.post("/auth/mobile/verify", json={"email": email, "token": code})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"user_id", "session", "profile_complete"}
    assert "refresh_token" not in r.text
    assert body["profile_complete"] is False
    assert body["session"]["session_type"] == "mobile"
    assert body["session"]["token_type"] == "bearer"
    user_id = UUID(body["user_id"])
    row = db.execute(
        text("SELECT email, system_role::text FROM users WHERE id = :i"), {"i": user_id}
    ).one()
    assert (row.email, row.system_role) == (email, "user")

    token = body["session"]["access_token"]
    r = client.post("/auth/profile", headers=_bearer(token), json=_PROFILE)
    assert r.status_code == 204, r.text
    saved = db.execute(
        text("SELECT full_name, date_of_birth::text, gender::text FROM users WHERE id = :i"),
        {"i": user_id},
    ).one()
    assert saved.full_name == _PROFILE["ho_ten"]
    assert saved.date_of_birth == _PROFILE["ngay_sinh"]

    second = _generated_email_otp(supabase, gotrue, email)
    r = client.post("/auth/mobile/verify", json={"email": email, "token": second})
    assert r.status_code == 200, r.text
    assert r.json()["profile_complete"] is True
    assert r.json()["user_id"] == str(user_id)


def test_wrong_email_otp_returns_401_without_provider_detail__AC2(client, supabase, gotrue):
    email = _new_email("it-wrong")
    r = client.post("/auth/mobile/otp", json={"email": email})
    assert r.status_code == 204, r.text
    code = _mail_otp(email)
    wrong = "000000" if code != "000000" else "111111"

    r = client.post("/auth/mobile/verify", json={"email": email, "token": wrong})

    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid credentials"}
    # Mã đúng vẫn dùng được: lần sai không làm hỏng phiên đăng nhập.
    r = client.post("/auth/mobile/verify", json={"email": email, "token": code})
    assert r.status_code == 200, r.text


def test_profile_rejects_future_date_of_birth__AC5(client, supabase, gotrue):
    email = _new_email("it-dob")
    client.post("/auth/mobile/otp", json={"email": email})
    token = client.post(
        "/auth/mobile/verify", json={"email": email, "token": _mail_otp(email)}
    ).json()["session"]["access_token"]

    r = client.post(
        "/auth/profile", headers=_bearer(token), json={**_PROFILE, "ngay_sinh": "2099-01-01"}
    )

    assert r.status_code == 422
    assert r.json() == {"detail": "invalid_date_of_birth"}


# --- Mobile: số điện thoại test_otp ------------------------------------------------------------


def test_phone_test_otp_login__AC6(client, supabase):
    r = client.post("/auth/mobile/otp", json={"phone": TEST_PHONE})
    assert r.status_code == 204, r.text

    r = client.post("/auth/mobile/verify", json={"phone": TEST_PHONE, "token": TEST_PHONE_OTP})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session"]["session_type"] == "mobile"
    assert set(body) == {"user_id", "session", "profile_complete"}


def test_both_identifiers_rejected_before_calling_provider__AC5(client, supabase):
    r = client.post("/auth/mobile/otp", json={"phone": TEST_PHONE, "email": _new_email("it-both")})

    assert r.status_code == 422
    assert r.json() == {"detail": "login_identifier_required"}


# --- Bearer: chỉ phiên do backend cấp ----------------------------------------------------------


def test_supabase_access_token_rejected_as_bearer__AC3b(client, supabase, gotrue, password_user):
    email, password, _ = password_user
    r = gotrue.post(
        "/token",
        params={"grant_type": "password"},
        headers={"apikey": supabase["SUPABASE_ANON_KEY"]},
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    supabase_token = r.json()["access_token"]

    r = client.post("/auth/profile", headers=_bearer(supabase_token), json=_PROFILE)

    assert r.status_code == 401


def test_app_session_accepted_as_bearer__AC3b(client, supabase, password_user, auth):
    _, _, user_id = password_user

    r = client.post("/auth/profile", headers=auth(user_id), json=_PROFILE)

    assert r.status_code == 204, r.text


# --- Admin Web ---------------------------------------------------------------------------------


def test_admin_login_and_refresh__AC7_AC3a(client, dev_admin):
    email, user_id = dev_admin

    r = client.post("/auth/admin/login", json={"email": email, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"user_id", "session"}
    assert "refresh_token" not in r.text
    assert body["user_id"] == str(user_id)
    assert body["session"]["session_type"] == "admin_web"
    assert body["session"]["expires_in"] == 1200

    r = client.post(
        "/auth/admin/session/refresh", json={"session_token": body["session"]["access_token"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["session"]["session_type"] == "admin_web"


def test_admin_wrong_password_returns_401_without_provider_detail__AC1(client, dev_admin):
    email, _ = dev_admin

    r = client.post("/auth/admin/login", json={"email": email, "password": "wrong-password"})

    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid credentials"}


def test_non_admin_admin_login_forbidden__AC7(client, password_user):
    email, password, _ = password_user

    r = client.post("/auth/admin/login", json={"email": email, "password": password})

    assert r.status_code == 403
    assert r.json() == {"detail": "admin_required"}


def test_refresh_after_admin_role_removed_is_forbidden__AC7(client, dev_admin, db):
    """Quyền đọc từ DB ở mỗi request: gỡ quyền admin có hiệu lực ngay ở lần refresh kế tiếp."""
    email, user_id = dev_admin
    token = client.post(
        "/auth/admin/login", json={"email": email, "password": ADMIN_PASSWORD}
    ).json()["session"]["access_token"]
    db.execute(text("UPDATE users SET system_role = 'user' WHERE id = :i"), {"i": user_id})

    r = client.post("/auth/admin/session/refresh", json={"session_token": token})

    assert r.status_code == 403
    assert r.json() == {"detail": "admin_required"}


def test_expired_admin_session_cannot_refresh__AC3b(client, dev_admin):
    from drugtime.modules.identity.application.sign_in import issue_app_session
    from drugtime.modules.identity.domain.user import SessionType

    _, user_id = dev_admin
    expired = issue_app_session(
        user_id, SessionType.ADMIN_WEB, datetime.now(UTC) - timedelta(hours=1)
    ).token

    r = client.post("/auth/admin/session/refresh", json={"session_token": expired})

    assert r.status_code == 401


def test_mobile_session_cannot_refresh_admin_session__AC3b(client, dev_admin, auth):
    _, user_id = dev_admin
    mobile_token = auth(user_id)["Authorization"].removeprefix("Bearer ")

    r = client.post("/auth/admin/session/refresh", json={"session_token": mobile_token})

    assert r.status_code == 401


# --- /auth/register đã gỡ ----------------------------------------------------------------------


def test_register_route_removed_and_creates_nothing__AC3c(client, supabase, db):
    email = _new_email("it-register")

    r = client.post(
        "/auth/register",
        json={"email": email, "ho_ten": "X", "ngay_sinh": "1990-01-01", "gioi_tinh": "nam"},
    )

    assert r.status_code in (404, 405)
    assert _auth_user_count(db, email) == 0
    users = db.execute(text("SELECT count(*) FROM users WHERE email = :e"), {"e": email})
    assert users.scalar_one() == 0
