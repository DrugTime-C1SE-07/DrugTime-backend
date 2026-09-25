from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from drugtime.modules.identity.application import sign_in
from drugtime.modules.identity.domain.user import UserRecord
from drugtime.shared.config import get_settings
from drugtime.shared.errors import DomainError, Forbidden, Unauthorized


class FakeAuth:
    def __init__(self, user_id):
        self.user_id = user_id
        self.deleted = []
        self.otp_requests = []

    def create_user_without_password(self, *, email, phone):
        return {"id": str(self.user_id), "email": email, "phone": phone}

    def login_with_password(self, *, email, password):
        return {"user": {"id": str(self.user_id)}, "email": email}

    def request_otp(self, *, phone, email, create_user=False):
        self.otp_requests.append((phone, email, create_user))

    def verify_otp(self, *, phone, email, token):
        return {"user": {"id": str(self.user_id)}, "token": token}

    def delete_account(self, user_id):
        self.deleted.append(user_id)


class FakeUsers:
    def __init__(self, user=None, fail_create=False):
        self.user = user
        self.fail_create = fail_create
        self.created_profile = None

    def get(self, user_id):
        return self.user

    def create_minimal(self, user_id, *, phone, email):
        pass

    def create_registered_user(self, profile):
        if self.fail_create:
            raise RuntimeError("db down")
        self.created_profile = profile

    def device_tokens(self, user_ids, platform):
        return []

    def erase(self, user_id):
        pass


@pytest.fixture(autouse=True)
def session_secret(monkeypatch):
    monkeypatch.setenv("SESSION_JWT_SECRET", "test-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_register_creates_supabase_user_without_password_and_local_profile():
    user_id = uuid4()
    auth = FakeAuth(user_id)
    users = FakeUsers()

    result = sign_in.register_user(
        auth,
        users,
        email="USER@example.com",
        ho_ten="Nguyen Van A",
        so_dien_thoai="0901234567",
        ngay_sinh=date(1990, 1, 1),
        gioi_tinh="nam",
        loai_tai_khoan="patient",
        now=datetime(2026, 9, 25, tzinfo=UTC),
    )

    assert result["user_id"] == str(user_id)
    assert users.created_profile.email == "user@example.com"
    assert users.created_profile.phone_number == "+84901234567"
    assert users.created_profile.full_name == "Nguyen Van A"


def test_register_compensates_supabase_user_when_local_create_fails():
    user_id = uuid4()
    auth = FakeAuth(user_id)

    with pytest.raises(RuntimeError):
        sign_in.register_user(
            auth,
            FakeUsers(fail_create=True),
            email="user@example.com",
            ho_ten="Nguyen Van A",
            so_dien_thoai="+84901234567",
            ngay_sinh=date(1990, 1, 1),
            gioi_tinh="nam",
            loai_tai_khoan="patient",
            now=datetime(2026, 9, 25, tzinfo=UTC),
        )

    assert auth.deleted == [user_id]


def test_mobile_otp_requires_exactly_one_identifier():
    auth = FakeAuth(uuid4())
    with pytest.raises(DomainError):
        sign_in.request_mobile_otp(auth, phone=None, email=None)
    with pytest.raises(DomainError):
        sign_in.request_mobile_otp(auth, phone="+84901234567", email="u@example.com")


def test_mobile_verify_rejects_erased_user():
    user_id = uuid4()
    auth = FakeAuth(user_id)
    users = FakeUsers(UserRecord(user_id, is_admin=False, erased=True))

    with pytest.raises(Unauthorized):
        sign_in.verify_mobile_otp(
            auth,
            users,
            phone="+84901234567",
            email=None,
            token="123456",
            now=datetime(2026, 9, 25, tzinfo=UTC),
        )


def test_admin_login_rejects_non_admin():
    user_id = uuid4()
    auth = FakeAuth(user_id)
    users = FakeUsers(UserRecord(user_id, is_admin=False, erased=False))

    with pytest.raises(Forbidden):
        sign_in.login_admin(
            auth,
            users,
            email="user@example.com",
            password="password-123",
            now=datetime(2026, 9, 25, tzinfo=UTC),
        )


def test_admin_session_expires_after_20_minutes():
    user_id = uuid4()
    session = sign_in.issue_app_session(
        user_id, sign_in.SessionType.ADMIN_WEB, datetime(2026, 9, 25, tzinfo=UTC)
    )

    assert session.expires_in_seconds == int(timedelta(minutes=20).total_seconds())


def test_mobile_session_targets_10_days():
    user_id = uuid4()
    session = sign_in.issue_app_session(
        user_id, sign_in.SessionType.MOBILE, datetime(2026, 9, 25, tzinfo=UTC)
    )

    assert session.expires_in_seconds == int(timedelta(days=10).total_seconds())
