"""Adapter Pexels (task 5.11: AC8, AC9). HTTP giả qua MockTransport; không dùng key thật."""

import httpx
import pytest

from drugtime.modules.ai_meal.adapters.outbound.pexels_client import (
    MAX_BYTES,
    PexelsClient,
    sniff_content_type,
)
from drugtime.modules.ai_meal.domain.errors import ImageSearchFailed

KEY = "fake-pexels-key"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PHOTO = {
    "id": 111,
    "url": "https://www.pexels.com/photo/example-111/",
    "photographer": "Nguyễn Văn A",
    "photographer_url": "https://www.pexels.com/@example-a",
    "src": {"large": "https://images.pexels.com/photos/111/large.jpeg"},
}


def _client(search=None, download=None):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "api.pexels.com":
            return search(request) if search else httpx.Response(200, json={"photos": [PHOTO]})
        return download(request) if download else httpx.Response(200, content=JPEG)

    client = PexelsClient(api_key=KEY, timeout_seconds=1,
                          http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return client, seen


def test_search_sends_only_query_and_technical_params__AC9():
    client, seen = _client()
    found = client.find("vietnamese sour fish soup")
    search, download = seen
    assert dict(search.url.params) == {
        "query": "vietnamese sour fish soup", "orientation": "landscape", "per_page": "5"}
    assert search.headers["authorization"] == KEY
    assert str(download.url) == PHOTO["src"]["large"]
    assert "authorization" not in download.headers  # key chỉ gửi tới API tìm kiếm
    assert found.content == JPEG and found.content_type == "image/jpeg"
    assert (found.provider_photo_id, found.photographer_name) == ("111", "Nguyễn Văn A")
    assert found.photographer_url == PHOTO["photographer_url"]
    assert found.source_url == PHOTO["url"]


def test_skips_incomplete_photos_and_picks_first_valid__AC7():
    broken = [{"id": 1}, {**PHOTO, "photographer": ""}, {**PHOTO, "src": {"large": "http://x"}}]
    client, _ = _client(search=lambda r: httpx.Response(200, json={"photos": [*broken, PHOTO]}))
    assert client.find("q").provider_photo_id == "111"


def _raise(exc_type):
    def handler(request):
        raise exc_type("boom", request=request)
    return handler


@pytest.mark.parametrize(
    ("search", "download", "reason"),
    [
        (lambda r: httpx.Response(200, json={"photos": []}), None, "no_result"),
        (lambda r: httpx.Response(429), None, "rate_limited"),
        (lambda r: httpx.Response(500), None, "upstream"),
        (lambda r: httpx.Response(401), None, "upstream"),
        (_raise(httpx.ReadTimeout), None, "timeout"),
        (_raise(httpx.ConnectError), None, "network"),
        (lambda r: httpx.Response(200, content=b"<html>"), None, "invalid_response"),
        (lambda r: httpx.Response(200, json=[1]), None, "invalid_response"),
        (None, lambda r: httpx.Response(404), "upstream"),
        (None, lambda r: httpx.Response(200, content=b"<html>not image</html>"), "not_image"),
        (None, lambda r: httpx.Response(200, content=b""), "not_image"),
        (None, lambda r: httpx.Response(200, content=b"\xff\xd8\xff" + b"0" * MAX_BYTES),
         "too_large"),
        (None, _raise(httpx.ReadTimeout), "timeout"),
    ],
)
def test_failures_map_to_reason_without_secret__AC8(search, download, reason):
    client, _ = _client(search, download)
    with pytest.raises(ImageSearchFailed) as exc:
        client.find("q")
    assert exc.value.reason == reason
    assert KEY not in str(exc.value) and exc.value.__cause__ is None


def test_exactly_two_mb_accepted__AC8():
    body = b"\xff\xd8\xff" + b"0" * (MAX_BYTES - 3)
    client, _ = _client(download=lambda r: httpx.Response(200, content=body))
    assert len(client.find("q").content) == MAX_BYTES


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"\xff\xd8\xff\xdb", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n0000", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"GIF89a", None),
        (b"RIFF\x00\x00\x00\x00WAVE", None),
    ],
)
def test_sniff_content_type(head, expected):
    assert sniff_content_type(head) == expected


def test_repr_hides_key__AC9():
    client, _ = _client()
    assert KEY not in repr(client)
