"""Tìm và tải ảnh minh họa món trên Pixabay (adhoc-20261120-pixabay-meal-images, AC1–AC4).

- Chỉ `image_query` được gửi đi (cộng tham số kỹ thuật cố định); không có định danh, thuốc,
  bệnh nền hay dị ứng (QD-41). Không lọc `category`.
- Pixabay nhận key qua query string `key=`, nên URL tìm kiếm chứa key. Logger `httpx` ghi URL
  request ở mức INFO: `_RedactKeyFilter` thay giá trị `key=` bằng `***` trước khi ghi.
  Mọi lỗi httpx được đổi thành `ImageSearchFailed` với mã lý do (không mang URL), ném
  `from None` để traceback không kèm exception gốc.
- Không retry; timeout theo cấu hình. Ảnh chỉ tải từ host `pixabay.com` (hoặc subdomain),
  bằng stream, dừng ngay khi vượt 2 MB. Định dạng kiểm bằng magic bytes (JPEG/PNG/WebP),
  không tin header `Content-Type`.
- Ảnh được tải về và lưu ở Storage ngay, theo yêu cầu "không hotlink" của Pixabay.
"""

import logging
import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from drugtime.modules.ai_meal.application.ports import FoundImage
from drugtime.modules.ai_meal.domain.errors import ImageSearchFailed

SEARCH_URL = "https://pixabay.com/api/"
MAX_BYTES = 2 * 1024 * 1024
PER_PAGE = 5
SEARCH_PARAMS = {
    "image_type": "photo",
    "orientation": "horizontal",
    "safesearch": "true",
    "lang": "en",
    "per_page": str(PER_PAGE),
}
IMAGE_HOST = "pixabay.com"

_KEY_IN_URL = re.compile(r"([?&]key=)[^&\s\"'#]+")


class _RedactKeyFilter(logging.Filter):
    """Thay giá trị `key=` trong message log (URL request của httpx) bằng `***`."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _KEY_IN_URL.sub(r"\1***", message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


_REDACT_FILTER = _RedactKeyFilter()
_LOGGERS_WITH_URLS = ("httpx", "httpcore")


def install_log_redaction() -> None:
    """Gắn filter vào logger của httpx/httpcore. Idempotent."""
    for name in _LOGGERS_WITH_URLS:
        logger = logging.getLogger(name)
        if _REDACT_FILTER not in logger.filters:
            logger.addFilter(_REDACT_FILTER)


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


def _https(url: str) -> bool:
    return url.startswith("https://")


def _image_host_allowed(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == IMAGE_HOST or host.endswith("." + IMAGE_HOST)


def _pick(hit: Any) -> dict[str, str] | None:
    if not isinstance(hit, dict):
        return None
    picked = {
        "id": _str(hit, "id", 64),
        "user": _str(hit, "user", 120),
        "user_id": _str(hit, "user_id", 64),
        "page_url": _str(hit, "pageURL"),
        "image_url": _str(hit, "largeImageURL"),
    }
    if not all(picked.values()):
        return None
    if not (_https(picked["page_url"]) and _https(picked["image_url"])):
        return None
    if not _image_host_allowed(picked["image_url"]):
        return None
    profile = f"https://pixabay.com/users/{quote(picked['user'], safe='')}-{picked['user_id']}/"
    if len(profile) > 500:
        return None
    picked["profile_url"] = profile
    return picked  # type: ignore[return-value]


class PixabayClient:
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
        install_log_redaction()

    def __repr__(self) -> str:
        return "PixabayClient()"

    def find(self, query: str) -> FoundImage:
        hit = self._first_hit(query)
        content, content_type = self._download(hit["image_url"])
        return FoundImage(
            content=content,
            content_type=content_type,
            provider_photo_id=hit["id"],
            photographer_name=hit["user"],
            photographer_url=hit["profile_url"],
            source_url=hit["page_url"],
        )

    def _first_hit(self, query: str) -> dict[str, str]:
        try:
            r = self._client.get(
                SEARCH_URL,
                params={"key": self._key, "q": query, **SEARCH_PARAMS},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise ImageSearchFailed("timeout") from None
        except httpx.HTTPError:
            raise ImageSearchFailed("network") from None
        if r.status_code == 429:
            raise ImageSearchFailed("rate_limited")
        if not r.is_success:
            raise ImageSearchFailed("upstream")
        try:
            body: Any = r.json()
        except ValueError:
            raise ImageSearchFailed("invalid_response") from None
        hits = body.get("hits") if isinstance(body, dict) else None
        if not isinstance(hits, list):
            raise ImageSearchFailed("invalid_response")
        for hit in hits:
            picked = _pick(hit)
            if picked is not None:
                return picked
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
        except httpx.HTTPError:
            raise ImageSearchFailed("network") from None
        content = b"".join(chunks)
        content_type = sniff_content_type(content[:16])
        if not content or content_type is None:
            raise ImageSearchFailed("not_image")
        return content, content_type
