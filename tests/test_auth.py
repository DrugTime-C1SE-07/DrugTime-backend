"""Focused tests for Supabase Auth integration: register, login, token validation, user sync."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.mock_db import db
from app.core.supabase_client import reset_supabase_client

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset database and supabase client before each test."""
    db.reset()
    reset_supabase_client()
    yield
    reset_supabase_client()


# ═══════════════════════════════════════════════════
# Helper: Mock Supabase user/session objects
# ═══════════════════════════════════════════════════

def _make_mock_supabase_user(user_id="sb-uuid-patient-1", email="patient@example.com", user_metadata=None):
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.user_metadata = user_metadata or {"ho_ten": "Nguyễn Văn Test"}
    return user


def _make_mock_session(access_token="mock-access-token-xyz", refresh_token="mock-refresh-token-abc", expires_in=3600):
    session = MagicMock()
    session.access_token = access_token
    session.refresh_token = refresh_token
    session.expires_in = expires_in
    return session


def _make_mock_auth_response(user=None, session=None):
    resp = MagicMock()
    resp.user = user or _make_mock_supabase_user()
    resp.session = session or _make_mock_session()
    return resp


def _mock_supabase_client():
    """Create a mock Supabase client with auth methods."""
    mock_client = MagicMock()
    return mock_client


# ═══════════════════════════════════════════════════
# Patient Registration
# ═══════════════════════════════════════════════════

class TestPatientRegistration:

    @patch("app.routers.auth.get_supabase_client")
    def test_patient_registration_success(self, mock_get_client):
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_up.return_value = _make_mock_auth_response(
            user=_make_mock_supabase_user(user_id="sb-patient-new", email="new.patient@example.com"),
        )
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/register", json={
            "email": "new.patient@example.com",
            "password": "securepass123",
            "ho_ten": "Nguyễn Văn Mới",
            "loai_tai_khoan": "benh_nhan",
            "ngay_sinh": "1990-01-15",
            "gioi_tinh": "nam",
            "so_dien_thoai": "0901234567"
        })

        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        assert data["data"]["user"]["id"] == "sb-patient-new"
        assert data["data"]["user"]["ho_ten"] == "Nguyễn Văn Mới"
        assert data["data"]["user"]["vai_tro_he_thong"] == "user"
        assert data["data"]["access_token"] == "mock-access-token-xyz"
        assert data["data"]["token_type"] == "bearer"
        assert data["data"]["refresh_token"] is not None

        # Verify user was synced to DrugTime db
        assert "sb-patient-new" in db.users
        assert db.users["sb-patient-new"]["ho_ten"] == "Nguyễn Văn Mới"
        assert db.users["sb-patient-new"]["ngay_sinh"] == "1990-01-15"

    def test_patient_registration_validation_missing_email(self):
        """Registration with missing email should return 422."""
        res = client.post("/api/v1/auth/register", json={
            "password": "securepass123",
            "ho_ten": "Test"
        })
        assert res.status_code == 422
        body = res.json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_patient_registration_validation_short_password(self):
        """Registration with password too short should return 422."""
        res = client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "123",
            "ho_ten": "Test"
        })
        assert res.status_code == 422

    def test_patient_registration_validation_invalid_email(self):
        """Registration with invalid email format should return 422."""
        res = client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "securepass123",
            "ho_ten": "Test"
        })
        assert res.status_code == 422

    def test_patient_registration_validation_missing_ho_ten(self):
        """Registration without ho_ten should return 422."""
        res = client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "securepass123"
        })
        assert res.status_code == 422

    @patch("app.routers.auth.get_supabase_client")
    def test_patient_registration_duplicate_email(self, mock_get_client):
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_up.side_effect = Exception("User already registered")
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/register", json={
            "email": "existing@example.com",
            "password": "securepass123",
            "ho_ten": "Test User"
        })

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"

    @patch("app.routers.auth.get_supabase_client")
    def test_patient_registration_supabase_error(self, mock_get_client):
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_up.side_effect = Exception("Internal server error")
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "securepass123",
            "ho_ten": "Test User"
        })

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "REGISTRATION_FAILED"

    def test_patient_registration_supabase_unavailable(self):
        """Registration when Supabase is not configured should return 503."""
        res = client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "securepass123",
            "ho_ten": "Test User"
        })

        assert res.status_code == 503
        assert res.json()["error"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


# ═══════════════════════════════════════════════════
# Family Member Registration
# ═══════════════════════════════════════════════════

class TestFamilyMemberRegistration:

    @patch("app.routers.auth.get_supabase_client")
    def test_family_member_registration_success(self, mock_get_client):
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_up.return_value = _make_mock_auth_response(
            user=_make_mock_supabase_user(user_id="sb-family-new", email="family@example.com"),
        )
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/register", json={
            "email": "family@example.com",
            "password": "familypass123",
            "ho_ten": "Trần Thị Người Thân",
            "loai_tai_khoan": "nguoi_than",
            "so_dien_thoai": "0909876543"
        })

        assert res.status_code == 201
        data = res.json()
        assert data["success"] is True
        assert data["data"]["user"]["id"] == "sb-family-new"
        assert data["data"]["user"]["ho_ten"] == "Trần Thị Người Thân"
        assert data["data"]["access_token"] is not None

        # Verify DrugTime user synced
        assert "sb-family-new" in db.users

    @patch("app.routers.auth.get_supabase_client")
    def test_family_member_registration_validation_failure(self, mock_get_client):
        """Invalid loai_tai_khoan should fail validation."""
        res = client.post("/api/v1/auth/register", json={
            "email": "family@example.com",
            "password": "familypass123",
            "ho_ten": "Test",
            "loai_tai_khoan": "invalid_role"
        })
        assert res.status_code == 422

    @patch("app.routers.auth.get_supabase_client")
    def test_family_member_registration_supabase_failure(self, mock_get_client):
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_up.return_value = _make_mock_auth_response(
            user=None,  # No user returned
            session=None,
        )
        # Mock user as None
        mock_client.auth.sign_up.return_value.user = None
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/register", json={
            "email": "family@example.com",
            "password": "familypass123",
            "ho_ten": "Test User",
            "loai_tai_khoan": "nguoi_than"
        })

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "REGISTRATION_FAILED"


# ═══════════════════════════════════════════════════
# Login
# ═══════════════════════════════════════════════════

class TestLogin:

    @patch("app.routers.auth.get_supabase_client")
    def test_login_success(self, mock_get_client):
        # Pre-seed a DrugTime user
        db.users["sb-login-user"] = {
            "id": "sb-login-user",
            "ho_ten": "Nguyễn Đăng Nhập",
            "ngay_sinh": "1985-06-15",
            "gioi_tinh": "nam",
            "so_dien_thoai": "0901111111",
            "che_do_nguoi_cao_tuoi": False,
            "vai_tro_he_thong": "user",
            "created_at": "2026-09-01T08:00:00Z"
        }

        mock_client = _mock_supabase_client()
        mock_client.auth.sign_in_with_password.return_value = _make_mock_auth_response(
            user=_make_mock_supabase_user(user_id="sb-login-user", email="login@example.com"),
        )
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/login", json={
            "email": "login@example.com",
            "password": "correctpass123"
        })

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["data"]["user"]["id"] == "sb-login-user"
        assert data["data"]["user"]["ho_ten"] == "Nguyễn Đăng Nhập"
        assert data["data"]["access_token"] == "mock-access-token-xyz"
        assert data["data"]["token_type"] == "bearer"

    @patch("app.routers.auth.get_supabase_client")
    def test_login_creates_drugtime_user_if_not_exists(self, mock_get_client):
        """Login should auto-sync user to DrugTime db if not already present."""
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_in_with_password.return_value = _make_mock_auth_response(
            user=_make_mock_supabase_user(
                user_id="sb-new-login",
                email="newlogin@example.com",
                user_metadata={"ho_ten": "Người Dùng Mới Login"}
            ),
        )
        mock_get_client.return_value = mock_client

        assert "sb-new-login" not in db.users

        res = client.post("/api/v1/auth/login", json={
            "email": "newlogin@example.com",
            "password": "pass123456"
        })

        assert res.status_code == 200
        assert "sb-new-login" in db.users
        assert db.users["sb-new-login"]["ho_ten"] == "Người Dùng Mới Login"

    @patch("app.routers.auth.get_supabase_client")
    def test_login_invalid_credentials(self, mock_get_client):
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_in_with_password.side_effect = Exception("Invalid login credentials")
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpass"
        })

        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    @patch("app.routers.auth.get_supabase_client")
    def test_login_generic_auth_failure(self, mock_get_client):
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_in_with_password.side_effect = Exception("Service unavailable")
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "somepass123"
        })

        assert res.status_code == 401
        assert res.json()["error"]["code"] == "LOGIN_FAILED"

    def test_login_validation_missing_password(self):
        res = client.post("/api/v1/auth/login", json={
            "email": "test@example.com"
        })
        assert res.status_code == 422

    def test_login_validation_invalid_email(self):
        res = client.post("/api/v1/auth/login", json={
            "email": "not-valid",
            "password": "pass123"
        })
        assert res.status_code == 422

    def test_login_supabase_unavailable(self):
        """Login when Supabase is not configured should return 503."""
        res = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "pass123"
        })
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


# ═══════════════════════════════════════════════════
# User Synchronization (sync-profile)
# ═══════════════════════════════════════════════════

class TestUserSynchronization:

    def test_sync_profile_creates_new_user(self):
        """sync-profile with a new user ID should create the DrugTime user."""
        res = client.post(
            "/api/v1/auth/sync-profile",
            headers={"Authorization": "Bearer usr-new-sync"},
            json={"ho_ten": "Người Mới Đồng Bộ", "ngay_sinh": "2000-01-01", "gioi_tinh": "nu"}
        )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["ho_ten"] == "Người Mới Đồng Bộ"

    def test_sync_profile_updates_existing_user(self):
        """sync-profile with an existing user should update their data."""
        res = client.post(
            "/api/v1/auth/sync-profile",
            headers={"Authorization": "Bearer usr-patient-1"},
            json={"ho_ten": "Tên Mới Cập Nhật", "so_dien_thoai": "0999999999"}
        )

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["ho_ten"] == "Tên Mới Cập Nhật"
        assert data["so_dien_thoai"] == "0999999999"

    def test_sync_profile_idempotent(self):
        """Calling sync-profile twice should not create duplicates."""
        payload = {"ho_ten": "Đồng Bộ Lặp", "ngay_sinh": "1995-05-05"}

        res1 = client.post(
            "/api/v1/auth/sync-profile",
            headers={"Authorization": "Bearer usr-idempotent-test"},
            json=payload
        )
        assert res1.status_code == 200

        res2 = client.post(
            "/api/v1/auth/sync-profile",
            headers={"Authorization": "Bearer usr-idempotent-test"},
            json=payload
        )
        assert res2.status_code == 200
        assert res2.json()["data"]["ho_ten"] == "Đồng Bộ Lặp"


# ═══════════════════════════════════════════════════
# Token Authentication (mock token flow)
# ═══════════════════════════════════════════════════

class TestTokenAuthentication:

    def test_valid_mock_token_returns_user(self):
        """A known mock token should resolve to the correct user."""
        res = client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer usr-patient-1"}
        )
        assert res.status_code == 200
        assert res.json()["data"]["id"] == "usr-patient-1"

    def test_invalid_auth_header_format(self):
        """Malformed Authorization header should return 401."""
        res = client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Basic dXNyOnBhc3M="}
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_TOKEN"

    def test_missing_auth_header_defaults_to_dev_user(self):
        """No auth header should fall back to dev user (usr-patient-1)."""
        res = client.get("/api/v1/users/me")
        assert res.status_code == 200
        assert res.json()["data"]["id"] == "usr-patient-1"

    @patch("app.core.security._verify_supabase_token")
    def test_valid_supabase_jwt_resolves_user(self, mock_verify):
        """A valid Supabase JWT should resolve the authenticated user."""
        mock_verify.return_value = {
            "sub": "usr-patient-1",
            "email": "patient@example.com",
            "user_metadata": {"ho_ten": "Nguyễn Văn Bệnh Nhân"}
        }

        res = client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.mock-jwt-token"}
        )

        assert res.status_code == 200
        assert res.json()["data"]["id"] == "usr-patient-1"

    @patch("app.core.security._verify_supabase_token")
    def test_valid_jwt_unsycned_user_resolves_minimal_identity(self, mock_verify):
        """A valid JWT for a user not yet in DrugTime should still resolve."""
        mock_verify.return_value = {
            "sub": "sb-unsycned-uuid",
            "email": "new@example.com",
            "user_metadata": {"ho_ten": "Chưa Đồng Bộ"}
        }

        # The user is NOT in db.users, so /users/me will 404
        # but the auth dependency should NOT 401
        res = client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer valid-jwt-for-unsynced"}
        )

        assert res.status_code == 404
        assert res.json()["error"]["code"] == "USER_NOT_FOUND"

    @patch("app.core.security._verify_supabase_token")
    def test_expired_jwt_falls_back_to_mock(self, mock_verify):
        """If JWT verification returns None (invalid/expired), mock fallback is used."""
        mock_verify.return_value = None

        # Token not in db.users, should use mock fallback
        res = client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer expired-jwt-token"}
        )

        # Falls through to mock fallback — returns usr-patient-1
        assert res.status_code == 200

    def test_authenticated_identity_from_token(self):
        """Authenticated user identity should come from the token, not from request body."""
        res = client.post(
            "/api/v1/auth/sync-profile",
            headers={"Authorization": "Bearer usr-admin-1"},
            json={"ho_ten": "Admin Đồng Bộ"}
        )
        assert res.status_code == 200
        # User ID in response should be usr-admin-1, not something from the request body
        assert res.json()["data"]["id"] == "usr-admin-1"


# ═══════════════════════════════════════════════════
# Contract Verification
# ═══════════════════════════════════════════════════

class TestContractVerification:

    @patch("app.routers.auth.get_supabase_client")
    def test_register_response_schema(self, mock_get_client):
        """Verify register response matches expected schema."""
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_up.return_value = _make_mock_auth_response()
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/register", json={
            "email": "schema@example.com",
            "password": "pass123456",
            "ho_ten": "Schema Test"
        })

        assert res.status_code == 201
        body = res.json()
        # Verify envelope
        assert "success" in body
        assert "data" in body
        assert "message" in body
        # Verify auth response shape
        auth_data = body["data"]
        assert "user" in auth_data
        assert "access_token" in auth_data
        assert "token_type" in auth_data
        # Verify user shape
        user = auth_data["user"]
        assert "id" in user
        assert "ho_ten" in user
        assert "vai_tro_he_thong" in user
        assert "created_at" in user

    @patch("app.routers.auth.get_supabase_client")
    def test_login_response_schema(self, mock_get_client):
        """Verify login response matches expected schema."""
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_in_with_password.return_value = _make_mock_auth_response()
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/login", json={
            "email": "login@example.com",
            "password": "pass123456"
        })

        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert "data" in body
        auth_data = body["data"]
        assert auth_data["token_type"] == "bearer"
        assert "user" in auth_data
        assert "access_token" in auth_data

    def test_error_response_schema(self):
        """Verify error response follows ErrorEnvelope structure."""
        res = client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "pass123456",
            "ho_ten": "Test"
        })
        # Supabase not configured → 503
        assert res.status_code == 503
        body = res.json()
        assert body["success"] is False
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]

    def test_validation_error_schema(self):
        """Verify 422 validation errors use project's ErrorEnvelope format."""
        res = client.post("/api/v1/auth/register", json={})
        assert res.status_code == 422
        body = res.json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert isinstance(body["error"]["details"], list)


# ═══════════════════════════════════════════════════
# Security
# ═══════════════════════════════════════════════════

class TestSecurity:

    @patch("app.routers.auth.get_supabase_client")
    def test_no_password_in_response(self, mock_get_client):
        """Password must never appear in any response."""
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_up.return_value = _make_mock_auth_response()
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/register", json={
            "email": "sec@example.com",
            "password": "secret123",
            "ho_ten": "Security Test"
        })

        response_text = res.text
        assert "secret123" not in response_text

    @patch("app.routers.auth.get_supabase_client")
    def test_no_supabase_internal_error_leakage(self, mock_get_client):
        """Internal Supabase error details should not leak to the client."""
        mock_client = _mock_supabase_client()
        mock_client.auth.sign_up.side_effect = Exception(
            "PostgresError: duplicate key value violates unique constraint on auth.users"
        )
        mock_get_client.return_value = mock_client

        res = client.post("/api/v1/auth/register", json={
            "email": "leak@example.com",
            "password": "pass123456",
            "ho_ten": "Leak Test"
        })

        response_text = res.text
        assert "PostgresError" not in response_text
        assert "duplicate key" not in response_text
        assert "auth.users" not in response_text
