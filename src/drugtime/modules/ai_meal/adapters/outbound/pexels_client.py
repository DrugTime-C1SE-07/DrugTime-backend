"""Tìm và tải ảnh minh họa món trên Pexels (task 5.11, AC7–AC9).

- Chỉ `image_query` được gửi đi (cộng tham số kỹ thuật `orientation`, `per_page`); không có
  định danh, thuốc, bệnh nền hay dị ứng (QD-41).
- Không retry; timeout theo cấu hình. Ảnh tải bằng stream, dừng ngay khi vượt 2 MB.
- Định dạng kiểm bằng magic bytes (JPEG/PNG/WebP), không tin header `Content-Type`.
- Lỗi chỉ mang mã lý do; không mang URL, header hay key.
"""

from typing import Any

import httpx

from drugtime.modules.ai_meal.application.ports import FoundImage
from drugtime.modules.ai_meal.domain.errors import ImageSearchFailed

SEARCH_URL = "https://api.pexels.com/v1/search"
MAX_BYTES = 2 * 1024 * 1024
PER_PAGE = 5


def sniff_content_type(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _str(obj: dict, key: str, max_len: int = 500) -> str | None:
    value = obj.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 1 <= len(value) <= max_len else None


class PexelsClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._key = api_key
        self._timeout = timeout_seconds
        self._client = http_client or httpx.Client()

    def __repr__(self) -> str:
        return "PexelsClient()"

    def find(self, query: str) -> FoundImage:
        photo = self._first_photo(query)
        content, content_type = self._download(photo["src"])
        return FoundImage(
            content=content,
            content_type=content_type,
            provider_photo_id=photo["id"],
            photographer_name=photo["photographer"],
            photographer_url=photo["photographer_url"],
            source_url=photo["url"],
        )

    def _first_photo(self, query: str) -> dict[str, str]:
        try:
            r = self._client.get(
                SEARCH_URL,
                params={"query": query, "orientation": "landscape", "per_page": PER_PAGE},
                headers={"Authorization": self._key},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise ImageSearchFailed("timeout") from None
        except httpx.TransportError:
            raise ImageSearchFailed("network") from None
        if r.status_code == 429:
            raise ImageSearchFailed("rate_limited")
        if not r.is_success:
            raise ImageSearchFailed("upstream")
        try:
            body: Any = r.json()
        except ValueError:
            raise ImageSearchFailed("invalid_response") from None
        photos = body.get("photos") if isinstance(body, dict) else None
        if not isinstance(photos, list):
            raise ImageSearchFailed("invalid_response")
        for photo in photos:
            if not isinstance(photo, dict) or not isinstance(photo.get("src"), dict):
                continue
            picked = {
                "id": _str(photo, "id", 64),
                "photographer": _str(photo, "photographer", 120),
                "photographer_url": _str(photo, "photographer_url"),
                "url": _str(photo, "url"),
                "src": _str(photo["src"], "large"),
            }
            if all(picked.values()) and all(
                picked[k].startswith("https://") for k in ("photographer_url", "url", "src")
            ):
                return picked  # type: ignore[return-value]
        raise ImageSearchFailed("no_result")

    def _download(self, url: str) -> tuple[bytes, str]:
        try:
            with self._client.stream("GET", url, timeout=self._timeout) as r:
                if not r.is_success:
                    raise ImageSearchFailed("upstream")
                chunks: list[bytes] = []
                size = 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ImageSearchFailed("too_large")
                    chunks.append(chunk)
        except httpx.TimeoutException:
            raise ImageSearchFailed("timeout") from None
        except httpx.TransportError:
            raise ImageSearchFailed("network") from None
        content = b"".join(chunks)
        content_type = sniff_content_type(content[:16])
        if not content or content_type is None:
            raise ImageSearchFailed("not_image")
        return content, content_type
