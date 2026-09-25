from uuid import UUID

import httpx

from drugtime.shared.config import get_settings


class SupabaseAuth:
    """Gọi Supabase Auth REST (/auth/v1). Không log OTP."""

    def __init__(self) -> None:
        s = get_settings()
        self._base = f"{s.supabase_url}/auth/v1"
        self._anon = s.supabase_anon_key
        self._service = s.supabase_service_key

    def _ident(self, phone: str | None, email: str | None) -> dict:
        return {"phone": phone} if phone else {"email": email}

    def create_user_without_password(self, *, email: str, phone: str) -> dict:
        headers = {"apikey": self._service, "Authorization": f"Bearer {self._service}"}
        r = httpx.post(
            f"{self._base}/admin/users",
            headers=headers,
            json={
                "email": email,
                "phone": phone,
                "email_confirm": True,
                "phone_confirm": True,
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def login_with_password(self, *, email: str, password: str) -> dict:
        r = httpx.post(
            f"{self._base}/token?grant_type=password",
            headers={"apikey": self._anon},
            json={"email": email, "password": password},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def request_otp(
        self, *, phone: str | None, email: str | None, create_user: bool = False
    ) -> None:
        r = httpx.post(
            f"{self._base}/otp",
            headers={"apikey": self._anon},
            json={**self._ident(phone, email), "create_user": create_user},
            timeout=10,
        )
        r.raise_for_status()

    def verify_otp(self, *, phone: str | None, email: str | None, token: str) -> dict:
        body = {**self._ident(phone, email), "token": token, "type": "sms" if phone else "email"}
        r = httpx.post(
            f"{self._base}/verify", headers={"apikey": self._anon}, json=body, timeout=10
        )
        r.raise_for_status()
        return r.json()

    def delete_account(self, user_id: UUID) -> None:
        headers = {"apikey": self._service, "Authorization": f"Bearer {self._service}"}
        r = httpx.delete(f"{self._base}/admin/users/{user_id}", headers=headers, timeout=10)
        if r.status_code != 404:  # 404 = đã xóa trước đó
            r.raise_for_status()
