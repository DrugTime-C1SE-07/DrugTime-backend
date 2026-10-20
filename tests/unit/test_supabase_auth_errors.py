"""Lỗi Supabase Auth được dịch sang 401/429/503 theo contract, không mang nội dung phản hồi gốc."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from drugtime.modules.identity.adapters.outbound.supabase_auth import SupabaseAuth
from drugtime.shared.errors import Conflict, ServiceUnavailable, TooManyRequests, Unauthorized

SECRET_BODY = (
    '{"error":"invalid_grant","error_description":"secret-supabase-detail lan@example.com"}'
)


def _auth(status: int | None = None, *, exc: Exception | None = None, body: str = SECRET_BODY):
    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        return httpx.Response(status, text=body)

    return SupabaseAuth(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _calls(auth: SupabaseAuth):
    return {
        "login": lambda: auth.login_with_password(email="a@b.vn", password="password-123"),
        "verify": lambda: auth.verify_otp(phone=None, email="a@b.vn", token="123456"),
        "request_otp": lambda: auth.request_otp(phone="+84900000001", email=None),
    }


@pytest.mark.parametrize("status", [400, 401, 422])
def test_login_bad_credentials_maps_to_unauthorized_without_body(status):
    with pytest.raises(Unauthorized) as err:
        _auth(status).login_with_password(email="a@b.vn", password="password-123")

    assert "secret-supabase-detail" not in str(err.value)
    assert "lan@example.com" not in str(err.value)


@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_verify_wrong_or_expired_otp_maps_to_unauthorized(status):
    with pytest.raises(Unauthorized):
        _auth(status).verify_otp(phone="+84900000001", email=None, token="000000")


@pytest.mark.parametrize("call", ["login", "verify", "request_otp"])
def test_rate_limited_maps_to_429(call):
    with pytest.raises(TooManyRequests) as err:
        _calls(_auth(429))[call]()

    assert str(err.value) == "rate_limited"


@pytest.mark.parametrize("call", ["login", "verify", "request_otp"])
@pytest.mark.parametrize(
    "status, exc",
    [
        (500, None),
        (502, None),
        (None, httpx.ConnectError("refused")),
        (None, httpx.ReadTimeout("slow")),
    ],
)
def test_server_error_timeout_and_connect_error_map_to_503(call, status, exc):
    with pytest.raises(ServiceUnavailable) as err:
        _calls(_auth(status, exc=exc))[call]()

    assert str(err.value) == "auth_provider_unavailable"


@pytest.mark.parametrize("status", [400, 422])
def test_request_otp_provider_4xx_maps_to_503(status):
    # Định dạng đã được backend kiểm trước; 4xx lúc gửi OTP là lỗi cấu hình provider (SMS chưa bật).
    with pytest.raises(ServiceUnavailable):
        _auth(status).request_otp(phone="+84900000001", email=None)


def test_success_passes_response_through():
    auth = _auth(200, body='{"user": {"id": "8d3f2c1a-5b6e-4f70-9a81-2c3d4e5f6a7b"}}')

    assert auth.verify_otp(phone=None, email="a@b.vn", token="123456")["user"]["id"]
    assert auth.request_otp(phone=None, email="a@b.vn") is None


def test_update_email_uses_server_admin_endpoint_for_given_user(monkeypatch):
    user_id = uuid4()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": str(user_id), "email": "new@example.com"})

    monkeypatch.setattr(
        "drugtime.modules.identity.adapters.outbound.supabase_auth.get_settings",
        lambda: SimpleNamespace(
            supabase_url="http://supabase.test",
            supabase_anon_key="anon",
            supabase_service_key="server-secret",
        ),
    )
    auth = SupabaseAuth(client=httpx.Client(transport=httpx.MockTransport(handler)))

    auth.update_email(user_id, "new@example.com")

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "PUT"
    assert request.url.path == f"/auth/v1/admin/users/{user_id}"
    assert request.headers["apikey"] == "server-secret"
    assert request.headers["authorization"] == "Bearer server-secret"
    assert request.read() == b'{"email":"new@example.com","email_confirm":true}'


def test_update_email_duplicate_is_generic_conflict_without_provider_body(monkeypatch):
    monkeypatch.setattr(
        "drugtime.modules.identity.adapters.outbound.supabase_auth.get_settings",
        lambda: SimpleNamespace(
            supabase_url="http://supabase.test",
            supabase_anon_key="anon",
            supabase_service_key="server-secret",
        ),
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                422,
                json={"code": "email_exists", "message": "private@example.com is taken"},
            )
        )
    )
    auth = SupabaseAuth(client=client)

    with pytest.raises(Conflict, match="email_change_unavailable") as err:
        auth.update_email(uuid4(), "private@example.com")

    assert "private@example.com" not in str(err.value)


def test_update_email_requires_service_key(monkeypatch):
    monkeypatch.setattr(
        "drugtime.modules.identity.adapters.outbound.supabase_auth.get_settings",
        lambda: SimpleNamespace(
            supabase_url="http://supabase.test",
            supabase_anon_key="anon",
            supabase_service_key="",
        ),
    )
    auth = SupabaseAuth(client=httpx.Client(transport=httpx.MockTransport(lambda _: None)))

    with pytest.raises(ServiceUnavailable, match="auth_provider_unavailable"):
        auth.update_email(uuid4(), "new@example.com")
