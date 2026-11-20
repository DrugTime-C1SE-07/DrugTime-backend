"""Adapter Pixabay (adhoc-20261120-pixabay-meal-images: AC1–AC4).

HTTP giả qua MockTransport (vẫn đi qua `httpx.Client` thật, kể cả logging); không dùng key thật.
"""

import logging

import httpx
import pytest

from drugtime.modules.ai_meal.adapters.outbound.pixabay_client import (
    MAX_BYTES,
    PixabayClient,
    sniff_content_type,
)
from drugtime.modules.ai_meal.domain.errors import ImageSearchFailed

KEY = "FAKE-pixabay-key-0123456789"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
HIT = {
    "id": 111,
    "pageURL": "https://pixabay.com/photos/example-111/",
    "user": "nguyen_van_a",
    "user_id": 222,
    "largeImageURL": "https://pixabay.com/get/g111_1280.jpg",
    "webformatURL": "https://pixabay.com/get/g111_640.jpg",
}


def _client(search=None, download=None):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/api/":
            return search(request) if search else httpx.Response(200, json={"hits": [HIT]})
        return download(request) if download else httpx.Response(200, content=JPEG)

    client = PixabayClient(api_key=KEY, timeout_seconds=1,
                           http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return client, seen


def test_search_sends_only_query_and_fixed_params__AC3():
    client, seen = _client()
    client.find("vietnamese sour fish soup")
    search, download = seen
    assert (search.url.scheme, search.url.host) == ("https", "pixabay.com")
    assert search.url.path == "/api/"
    assert dict(search.url.params) == {
        "key": KEY,
        "q": "vietnamese sour fish soup",
        "image_type": "photo",
        "orientation": "horizontal",
        "safesearch": "true",
        "lang": "en",
        "per_page": "5",
    }
    assert "category" not in search.url.params
    assert "authorization" not in search.headers
    assert str(download.url) == HIT["largeImageURL"]
    assert KEY not in str(download.url)  # key chỉ gửi tới API tìm kiếm


def test_maps_hit_to_found_image__AC1():
    client, _ = _client()
    found = client.find("q")
    assert found.content == JPEG and found.content_type == "image/jpeg"
    assert found.provider_photo_id == "111"
    assert found.photographer_name == "nguyen_van_a"
    assert found.photographer_url == "https://pixabay.com/users/nguyen_van_a-222/"
    assert found.source_url == HIT["pageURL"]


def test_profile_url_quotes_username__AC1():
    client, _ = _client(
        search=lambda r: httpx.Response(200, json={"hits": [{**HIT, "user": "a b/c"}]}))
    assert client.find("q").photographer_url == "https://pixabay.com/users/a%20b%2Fc-222/"


@pytest.mark.parametrize(
    "broken",
    [
        {"id": 1},
        "not-a-dict",
        {**HIT, "user": ""},
        {**HIT, "user_id": None},
        {**HIT, "pageURL": "http://pixabay.com/photos/x/"},
        {**HIT, "largeImageURL": "http://pixabay.com/get/x.jpg"},
        {**HIT, "largeImageURL": "https://evil.example/get/x.jpg"},
        {**HIT, "largeImageURL": "https://pixabay.com.evil.example/x.jpg"},
        {**HIT, "user": "u" * 121},
    ],
)
def test_skips_invalid_hits_and_picks_first_valid__AC2(broken):
    valid = {**HIT, "id": 999}
    client, seen = _client(
        search=lambda r: httpx.Response(200, json={"hits": [broken, valid]}))
    assert client.find("q").provider_photo_id == "999"
    assert seen[1].url.host == "pixabay.com"


def test_subdomain_image_host_allowed__AC2():
    hit = {**HIT, "largeImageURL": "https://cdn.pixabay.com/photo/x_1280.jpg"}
    client, seen = _client(search=lambda r: httpx.Response(200, json={"hits": [hit]}))
    client.find("q")
    assert seen[1].url.host == "cdn.pixabay.com"


def _raise(exc_type):
    def handler(request):
        if exc_type is httpx.TooManyRedirects:
            raise exc_type("boom", request=request)
        raise exc_type(f"boom {request.url}", request=request)
    return handler


FAILURES = [
    (lambda r: httpx.Response(200, json={"hits": []}), None, "no_result"),
    (lambda r: httpx.Response(200, json={"total": 0}), None, "invalid_response"),
    (lambda r: httpx.Response(429, text="API rate limit exceeded"), None, "rate_limited"),
    (lambda r: httpx.Response(500), None, "upstream"),
    (lambda r: httpx.Response(400, text="[ERROR 400] Invalid or missing API key"), None,
     "upstream"),
    (_raise(httpx.ReadTimeout), None, "timeout"),
    (_raise(httpx.ConnectError), None, "network"),
    (_raise(httpx.TooManyRedirects), None, "network"),
    (_raise(httpx.DecodingError), None, "network"),
    (lambda r: httpx.Response(200, content=b"<html>"), None, "invalid_response"),
    (lambda r: httpx.Response(200, json=[1]), None, "invalid_response"),
    (None, lambda r: httpx.Response(404), "upstream"),
    (None, lambda r: httpx.Response(200, content=b"<html>not image</html>"), "not_image"),
    (None, lambda r: httpx.Response(200, content=b""), "not_image"),
    (None, lambda r: httpx.Response(200, content=b"\xff\xd8\xff" + b"0" * MAX_BYTES),
     "too_large"),
    (None, _raise(httpx.ReadTimeout), "timeout"),
    (None, _raise(httpx.DecodingError), "network"),
]


@pytest.mark.parametrize(("search", "download", "reason"), FAILURES)
def test_failures_map_to_reason_without_secret__AC2_AC4(search, download, reason):
    client, _ = _client(search, download)
    with pytest.raises(ImageSearchFailed) as exc:
        client.find("q")
    assert exc.value.reason == reason
    assert KEY not in str(exc.value) and KEY not in repr(exc.value)
    assert exc.value.__cause__ is None
    if exc.value.__context__ is not None:
        assert exc.value.__suppress_context__ is True


def test_exactly_two_mb_accepted__AC2():
    body = b"\xff\xd8\xff" + b"0" * (MAX_BYTES - 3)
    client, _ = _client(download=lambda r: httpx.Response(200, content=body))
    assert len(client.find("q").content) == MAX_BYTES


@pytest.mark.parametrize(("search", "download", "reason"),
                         [(None, None, "ready"), *FAILURES])
def test_httpx_logs_never_contain_key__AC4(caplog, search, download, reason):
    caplog.set_level(logging.DEBUG)
    client, _ = _client(search, download)
    try:
        client.find("q")
    except ImageSearchFailed:
        pass
    assert KEY not in caplog.text
    requests = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    if requests:
        assert "key=***" in requests[0]


def test_search_request_is_logged_redacted__AC4(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    client, _ = _client()
    client.find("q")
    (search_log, _download_log) = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert "pixabay.com/api/" in search_log and "key=***" in search_log
    assert "q=q" in search_log  # phần còn lại của URL giữ nguyên


def test_redaction_installed_once():
    PixabayClient(api_key=KEY, timeout_seconds=1)
    PixabayClient(api_key=KEY, timeout_seconds=1)
    assert len(logging.getLogger("httpx").filters) == 1


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


def test_repr_hides_key__AC4():
    client, _ = _client()
    assert KEY not in repr(client)
