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

    def login_with_password(self, *, email, password):
        return {
            "user": {"id": str(self.user_id)},
            "access_token": "supabase-access",
            "refresh_token": "supabase-refresh",
        }

    def request_otp(self, *, phone, email, create_user=False):
        self.otp_requests.append((phone, email, create_user))

    def verify_otp(self, *, phone, email, token):
        return {
            "user": {"id": str(self.user_id)},
            "access_token": "supabase-access",
            "refresh_token": "supabase-refresh",
        }

    def delete_account(self, user_id):
        self.deleted.append(user_id)


class FakeUsers:
    def __init__(self, user=None):
        self.user = user

    def get(self, user_id):
        return self.user

    def create_minimal(self, user_id, *, phone, email):
        self.user = UserRecord(user_id, is_admin=False, erased=False, profile_complete=False)

    def update_profile(self, user_id, *, full_name, date_of_birth, gender):
        self.updated_profile = (user_id, full_name, date_of_birth, gender)

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


def test_mobile_otp_requires_exactly_one_identifier():
    auth = FakeAuth(uuid4())
    with pytest.raises(DomainError):
        sign_in.request_mobile_otp(auth, phone=None, email=None)
    with pytest.raises(DomainError):
        sign_in.request_mobile_otp(auth, phone="+84901234567", email="u@example.com")


def test_mobile_verify_auto_provisions_new_user_and_flags_incomplete_profile():
    user_id = uuid4()
    auth = FakeAuth(user_id)
    users = FakeUsers(user=None)

    result = sign_in.verify_mobile_otp(
        auth,
        users,
        phone="+84901234567",
        email=None,
        token="123456",
        now=datetime(2026, 9, 25, tzinfo=UTC),
    )

    assert result["profile_complete"] is False
    assert users.user is not None
    assert users.user.id == user_id


def test_mobile_verify_rejects_erased_user():
    user_id = uuid4()
    auth = FakeAuth(user_id)
    users = FakeUsers(UserRecord(user_id, is_admin=False, erased=True, profile_complete=True))

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
    users = FakeUsers(UserRecord(user_id, is_admin=False, erased=False, profile_complete=True))

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


NOW = datetime(2026, 9, 25, tzinfo=UTC)


def _user(user_id, *, admin=False, erased=False, complete=True):
    return UserRecord(user_id, is_admin=admin, erased=erased, profile_complete=complete)


def test_mobile_verify_response_has_no_supabase_field():
    user_id = uuid4()

    result = sign_in.verify_mobile_otp(
        FakeAuth(user_id),
        FakeUsers(_user(user_id)),
        phone=None,
        email="a@b.vn",
        token="123456",
        now=NOW,
    )

    assert set(result) == {"user_id", "session", "profile_complete"}
    assert "supabase" not in repr(result) and "refresh_token" not in repr(result)
    assert result["session"]["session_type"] == "mobile"


def test_admin_login_response_has_no_supabase_field():
    user_id = uuid4()

    result = sign_in.login_admin(
        FakeAuth(user_id),
        FakeUsers(_user(user_id, admin=True)),
        email="admin@b.vn",
        password="password-123",
        now=NOW,
    )

    assert set(result) == {"user_id", "session"}
    assert "supabase" not in repr(result) and "refresh_token" not in repr(result)
    assert result["session"]["session_type"] == "admin_web"


def _verify(user=None, **kw):
    user_id = user.id if user else uuid4()
    args = {"phone": None, "email": "a@b.vn", "token": "123456", **kw}
    return sign_in.verify_mobile_otp(FakeAuth(user_id), FakeUsers(user), now=NOW, **args)


def _admin_login(user=None, **kw):
    user_id = user.id if user else uuid4()
    args = {"email": "admin@b.vn", "password": "password-123", **kw}
    return sign_in.login_admin(FakeAuth(user_id), FakeUsers(user), now=NOW, **args)


def _profile(**kw):
    args = {"ho_ten": "Nguyễn Thị Lan", "ngay_sinh": date(1958, 4, 12), "gioi_tinh": "nu", **kw}
    return sign_in.complete_profile(FakeUsers(), user_id=uuid4(), now=NOW, **args)


@pytest.mark.parametrize(
    "call, error, code",
    [
        (
            lambda: sign_in.request_mobile_otp(FakeAuth(uuid4()), phone=None, email=None),
            DomainError,
            "login_identifier_required",
        ),
        (
            lambda: sign_in.request_mobile_otp(FakeAuth(uuid4()), phone="0901", email="a@b.vn"),
            DomainError,
            "login_identifier_required",
        ),
        (
            lambda: sign_in.request_mobile_otp(FakeAuth(uuid4()), phone=None, email="not-an-email"),
            DomainError,
            "invalid_email",
        ),
        (
            lambda: sign_in.request_mobile_otp(FakeAuth(uuid4()), phone="12ab", email=None),
            DomainError,
            "invalid_phone",
        ),
        (lambda: _verify(phone="+8412", email=None), DomainError, "invalid_phone"),
        (lambda: _admin_login(email="nope"), DomainError, "invalid_email"),
        (lambda: _admin_login(password="short"), DomainError, "password_too_short"),
        (lambda: _profile(ho_ten="   "), DomainError, "invalid_full_name"),
        (lambda: _profile(gioi_tinh="x"), DomainError, "invalid_gender"),
        (lambda: _profile(ngay_sinh=date(2026, 9, 26)), DomainError, "invalid_date_of_birth"),
        (lambda: _verify(_user(uuid4(), admin=True)), Forbidden, "admin_must_use_web"),
        (lambda: _admin_login(_user(uuid4(), admin=False)), Forbidden, "admin_required"),
    ],
)
def test_error_codes_are_stable(call, error, code):
    with pytest.raises(error) as err:
        call()

    assert str(err.value) == code


def test_blank_otp_is_treated_as_wrong_code():
    with pytest.raises(Unauthorized):
        _verify(_user(uuid4()), token="   ")


def test_refresh_rejects_user_whose_admin_role_was_removed():
    user_id = uuid4()
    now = datetime.now(UTC)
    token = sign_in.issue_app_session(user_id, sign_in.SessionType.ADMIN_WEB, now).token

    with pytest.raises(Forbidden) as err:
        sign_in.refresh_admin_session(
            FakeUsers(_user(user_id, admin=False)), session_token=token, now=now
        )

    assert str(err.value) == "admin_required"


def test_complete_profile_accepts_valid_profile():
    users = FakeUsers()
    user_id = uuid4()

    sign_in.complete_profile(
        users,
        user_id=user_id,
        ho_ten=" Nguyễn Thị Lan ",
        ngay_sinh=date(1958, 4, 12),
        gioi_tinh="NU",
        now=NOW,
    )

    assert users.updated_profile == (user_id, "Nguyễn Thị Lan", date(1958, 4, 12), "nu")


def test_onboarding_uses_same_vietnam_day_as_health_profile():
    from datetime import UTC

    users = FakeUsers()
    user_id = uuid4()
    sign_in.complete_profile(
        users,
        user_id=user_id,
        ho_ten="  Bao  ",
        ngay_sinh=date(2026, 10, 13),
        gioi_tinh=" MALE ",
        now=datetime(2026, 10, 12, 18, tzinfo=UTC),
    )
    assert users.updated_profile == (user_id, "Bao", date(2026, 10, 13), "male")
