"""Adapter Supabase Storage cho ảnh món (task 5.11: AC7, AC9). HTTP giả, không gọi mạng."""

import httpx
import pytest

from drugtime.modules.ai_meal.adapters.outbound.supabase_storage import SupabaseStorage
from drugtime.modules.ai_meal.domain.errors import StorageUnavailable

KEY = "service-key-SECRET-123"


def _storage(handler):
    return SupabaseStorage(
        base_url="http://sb.local/", service_key=KEY, bucket="meal-images",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_upload_posts_bytes_to_bucket_with_service_key__AC7():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"Key": "meal-images/42.jpg"})

    _storage(handler).upload("42.jpg", b"\xff\xd8\xffdata", "image/jpeg")
    (req,) = seen
    assert req.method == "POST"
    assert str(req.url) == "http://sb.local/storage/v1/object/meal-images/42.jpg"
    assert req.headers["authorization"] == f"Bearer {KEY}" and req.headers["apikey"] == KEY
    assert req.headers["content-type"] == "image/jpeg" and req.headers["x-upsert"] == "true"
    assert req.content == b"\xff\xd8\xffdata"


def test_download_returns_bytes__AC7():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/storage/v1/object/meal-images/42.jpg"
        return httpx.Response(200, content=b"img")

    assert _storage(handler).download("42.jpg") == b"img"


def test_path_cannot_escape_bucket():
    def handler(request):
        assert request.url.raw_path.endswith(b"/meal-images/..%2Fother")
        return httpx.Response(200, content=b"")

    _storage(handler).download("../other")


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(404, json={"error": f"not found {KEY}"}),
        lambda r: httpx.Response(500),
        lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("t", request=r)),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("x", request=r)),
    ],
)
def test_errors_become_storage_unavailable_without_secrets__AC9(handler):
    with pytest.raises(StorageUnavailable) as exc:
        _storage(handler).download("1.jpg")
    assert KEY not in str(exc.value) and "sb.local" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_repr_hides_key__AC9():
    assert KEY not in repr(_storage(lambda r: httpx.Response(200)))
