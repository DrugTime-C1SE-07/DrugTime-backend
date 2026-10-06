from uuid import UUID

import httpx

from drugtime.shared.config import get_settings
from drugtime.shared.errors import ServiceUnavailable, TooManyRequests, Unauthorized

_TIMEOUT = 10
_CREDENTIAL_ERRORS = {400, 401, 403, 404, 422}


def _raise_for_status(r: httpx.Response) -> None:
    if r.is_error:
        raise httpx.HTTPStatusError(
            f"{r.status_code} {r.reason_phrase} calling {r.request.url} — {r.text}",
            request=r.request,
            response=r,
        )


def _translate(r: httpx.Response, *, credentials: bool) -> None:
    """Đổi lỗi Supabase Auth sang lỗi theo contract; không mang nội dung phản hồi gốc."""
    if not r.is_error:
        return
    if r.status_code == 429:
        raise TooManyRequests("rate_limited")
    if credentials and r.status_code in _CREDENTIAL_ERRORS:
        raise Unauthorized("Invalid credentials")
    # Lỗi phía Supabase, hoặc lỗi cấu hình provider (ví dụ SMS chưa bật) khi gửi OTP.
    raise ServiceUnavailable("auth_provider_unavailable")


class SupabaseAuth:
    """Gọi Supabase Auth REST (/auth/v1). Không log OTP."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        s = get_settings()
        self._base = f"{s.supabase_url}/auth/v1"
        self._anon = s.supabase_anon_key
        self._service = s.supabase_service_key
        self._client = client

    def _ident(self, phone: str | None, email: str | None) -> dict:
        return {"phone": phone} if phone else {"email": email}

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        if self._client is not None:
            return self._client.request(method, url, timeout=_TIMEOUT, **kwargs)
        return httpx.request(method, url, timeout=_TIMEOUT, **kwargs)

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Gọi cho luồng đăng nhập: lỗi mạng/timeout thành 503 theo contract."""
        try:
            return self._request(method, url, **kwargs)
        except httpx.TransportError as exc:  # gồm cả TimeoutException
            raise ServiceUnavailable("auth_provider_unavailable") from exc

    def login_with_password(self, *, email: str, password: str) -> dict:
        r = self._send(
            "POST",
            f"{self._base}/token?grant_type=password",
            headers={"apikey": self._anon},
            json={"email": email, "password": password},
        )
        _translate(r, credentials=True)
        return r.json()

    def request_otp(
        self, *, phone: str | None, email: str | None, create_user: bool = False
    ) -> None:
        r = self._send(
            "POST",
            f"{self._base}/otp",
            headers={"apikey": self._anon},
            json={**self._ident(phone, email), "create_user": create_user},
        )
        _translate(r, credentials=False)

    def verify_otp(self, *, phone: str | None, email: str | None, token: str) -> dict:
        body = {**self._ident(phone, email), "token": token, "type": "sms" if phone else "email"}
        r = self._send("POST", f"{self._base}/verify", headers={"apikey": self._anon}, json=body)
        _translate(r, credentials=True)
        return r.json()

    def delete_account(self, user_id: UUID) -> None:
        headers = {"apikey": self._service, "Authorization": f"Bearer {self._service}"}
        r = self._request("DELETE", f"{self._base}/admin/users/{user_id}", headers=headers)
        if r.status_code != 404:  # 404 = đã xóa trước đó
            _raise_for_status(r)
