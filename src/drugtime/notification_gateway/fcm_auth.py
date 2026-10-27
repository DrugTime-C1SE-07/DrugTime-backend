"""Access token OAuth2 cho FCM HTTP v1 từ service account (grant JWT bearer, RFC 7523).

Dùng PyJWT[crypto] và httpx có sẵn thay cho google-auth. Không log khóa, assertion hay phản hồi
của máy chủ token.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"
# Lấy token mới trước khi hết hạn để không gửi bằng token sắp hết hạn.
REFRESH_MARGIN_SECONDS = 60


class NotificationConfigError(RuntimeError):
    """Cấu hình kênh báo thiếu hoặc hỏng; Worker dừng khi khởi động thay vì gửi giả."""


@dataclass(frozen=True)
class ServiceAccount:
    client_email: str
    private_key: str
    token_uri: str
    project_id: str


def load_service_account(path: str) -> ServiceAccount:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return ServiceAccount(
            client_email=data["client_email"],
            private_key=data["private_key"],
            token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
            project_id=data.get("project_id") or "",
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Không đưa nội dung file vào thông báo lỗi.
        raise NotificationConfigError(
            "FCM_CREDENTIALS_FILE is unreadable or not a service account JSON"
        ) from exc


class AccessTokenProvider:
    def __init__(
        self,
        account: ServiceAccount,
        client: httpx.Client,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._account = account
        self._client = client
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    def token(self) -> str:
        now = self._clock()
        if self._token is None or now >= self._expires_at - REFRESH_MARGIN_SECONDS:
            self._token, self._expires_at = self._fetch(now)
        return self._token

    def invalidate(self) -> None:
        self._token = None

    def _fetch(self, now: float) -> tuple[str, float]:
        issued = int(now)
        assertion = jwt.encode(
            {
                "iss": self._account.client_email,
                "scope": SCOPE,
                "aud": self._account.token_uri,
                "iat": issued,
                "exp": issued + 3600,
            },
            self._account.private_key,
            algorithm="RS256",
        )
        response = self._client.post(
            self._account.token_uri, data={"grant_type": GRANT_TYPE, "assertion": assertion}
        )
        if response.status_code != 200:
            raise RuntimeError(f"FCM access token request failed with HTTP {response.status_code}")
        body = response.json()
        return body["access_token"], issued + int(body.get("expires_in", 3600))
