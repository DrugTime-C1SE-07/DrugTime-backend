"""Supabase Storage REST cho ảnh món (task 5.11).

Chỉ backend (API và Worker) gọi, bằng service key phía server; client không bao giờ có key hay
URL kho lưu trữ (bất biến 1). Lỗi chỉ mang mã lý do, không mang URL, header hay key.
"""

from urllib.parse import quote

import httpx

from drugtime.modules.ai_meal.domain.errors import StorageUnavailable

_TIMEOUT = 10.0


class SupabaseStorage:
    def __init__(
        self,
        *,
        base_url: str,
        service_key: str,
        bucket: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base = f"{base_url.rstrip('/')}/storage/v1/object/{quote(bucket, safe='')}"
        self._key = service_key
        self._client = http_client

    def __repr__(self) -> str:
        return "SupabaseStorage()"

    def _send(
        self,
        method: str,
        path: str,
        *,
        extra_headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        url = f"{self._base}/{quote(path, safe='')}"
        headers = {"Authorization": f"Bearer {self._key}", "apikey": self._key,
                   **(extra_headers or {})}
        try:
            if self._client is not None:
                r = self._client.request(method, url, headers=headers, content=content,
                                         timeout=_TIMEOUT)
            else:
                r = httpx.request(method, url, headers=headers, content=content,
                                  timeout=_TIMEOUT)
        except httpx.TransportError:  # gồm cả TimeoutException
            raise StorageUnavailable("network") from None
        if not r.is_success:
            raise StorageUnavailable(f"status_{r.status_code}")
        return r

    def upload(self, path: str, content: bytes, content_type: str) -> None:
        self._send("POST", path, extra_headers={"Content-Type": content_type, "x-upsert": "true"},
                   content=content)

    def download(self, path: str) -> bytes:
        return self._send("GET", path).content
