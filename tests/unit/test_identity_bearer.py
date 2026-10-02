"""Bearer chỉ nhận phiên do backend cấp; token Supabase bị từ chối (AC3b)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from drugtime.modules.identity.adapters.inbound import dependencies
from drugtime.modules.identity.application import sign_in
from drugtime.modules.identity.domain.user import SessionType, UserRecord
from drugtime.shared.config import get_settings
from drugtime.shared.errors import Unauthorized

SESSION_SECRET = "session-secret-for-tests-0123456789abcdef"
SUPABASE_SECRET = "supabase-secret-for-tests-0123456789abcdef"


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    monkeypatch.setenv("SESSION_JWT_SECRET", SESSION_SECRET)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SUPABASE_SECRET)
    monkeypatch.setenv("SUPABASE_JWKS_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Users:
    def __init__(self, uow):
        pass

    def get(self, user_id):
        return UserRecord(user_id, is_admin=False, erased=False, profile_complete=True)


def _call(token: str):
    return dependencies.current_user(authorization=f"Bearer {token}", uow=object())


@pytest.fixture
def users(monkeypatch):
    monkeypatch.setattr(dependencies, "SqlUsers", _Users)


def _supabase_token(user_id, secret=SUPABASE_SECRET):
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_supabase_token_rejected(users):
    with pytest.raises(Unauthorized):
        _call(_supabase_token(uuid4()))


def test_supabase_shaped_token_signed_with_session_secret_rejected(users):
    # Kể cả khi chữ ký đúng secret phiên, aud của Supabase vẫn bị từ chối.
    with pytest.raises(Unauthorized):
        _call(_supabase_token(uuid4(), secret=SESSION_SECRET))


@pytest.mark.parametrize("session_type", [SessionType.MOBILE, SessionType.ADMIN_WEB])
def test_app_session_tokens_accepted(users, session_type):
    user_id = uuid4()
    token = sign_in.issue_app_session(user_id, session_type, datetime.now(UTC)).token

    assert _call(token).id == user_id


def test_expired_admin_session_rejected(users):
    issued = datetime.now(UTC) - timedelta(minutes=21)
    token = sign_in.issue_app_session(uuid4(), SessionType.ADMIN_WEB, issued).token

    with pytest.raises(Unauthorized):
        _call(token)


def test_unknown_session_type_rejected(users):
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "aud": "drugtime",
        "typ": "service",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }

    with pytest.raises(Unauthorized):
        _call(jwt.encode(payload, SESSION_SECRET, algorithm="HS256"))


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer "])
def test_missing_or_malformed_header_rejected(users, header):
    with pytest.raises(Unauthorized):
        dependencies.current_user(authorization=header, uow=object())
