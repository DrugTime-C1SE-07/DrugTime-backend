"""Endpoint ảnh món không giữ kết nối DB khi tải ảnh từ Storage (Postgres thật).

Task adhoc-20261120-meal-image-loading (AC1, AC2). App chạy bằng api_role với pool mặc định
(5 + 10 kết nối). Storage là bản giả: mọi request tải ảnh dừng ở một barrier chung, nên
20 request chỉ cùng tới được barrier khi không request nào đang giữ kết nối trong lúc tải.
Không dùng `sleep`.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from drugtime.main import create_app
from drugtime.modules.ai_meal.adapters.inbound import images_http
from drugtime.shared.db import get_engine

PARALLEL = 20  # lớn hơn pool mặc định (5 + 10)
JPEG = b"\xff\xd8\xff\xe0pool-test"


class BarrierStorage:
    """Mọi lượt tải chờ nhau ở barrier; ghi lại số kết nối pool đang bị giữ lúc đó."""

    def __init__(self, parties):
        self.barrier = threading.Barrier(parties, timeout=15)
        self.checked_out = []

    def download(self, path):
        self.barrier.wait()  # BrokenBarrierError → 500 nếu có request kẹt chờ pool
        self.checked_out.append(get_engine().pool.checkedout())
        return JPEG


def ready_images(db, n):
    ids = []
    for _ in range(n):
        tag = uuid4().hex[:12]
        ids.append(db.execute(text(
            "INSERT INTO meal_images (dish_key, image_query, status, storage_path, content_type,"
            " size_bytes, provider, provider_photo_id, photographer_name, photographer_url,"
            " source_url) VALUES (:k, 'pool test dish', 'ready', :p, 'image/jpeg', :s,"
            " 'pixabay', '1', 'tester', 'https://pixabay.com/users/tester-1/',"
            " 'https://pixabay.com/photos/pool-1/') RETURNING id"),
            {"k": f"pool-{tag}", "p": f"pool-{tag}.jpg", "s": len(JPEG)}).scalar_one())
    return ids


@pytest.fixture
def app_with(request):
    app = create_app()

    def install(storage=None, store=None):
        if storage is not None:
            app.dependency_overrides[images_http.get_image_storage] = lambda: storage
        if store is not None:
            app.dependency_overrides[images_http.get_image_store] = lambda: store
        return app

    return install


def test_parallel_content_requests_all_200_without_holding_connections__AC1(
    db, make, auth, app_with
):
    user = make.user()
    ids = ready_images(db, PARALLEL)
    storage = BarrierStorage(PARALLEL)
    with TestClient(app_with(storage=storage)) as client:
        headers = auth(user)
        with ThreadPoolExecutor(PARALLEL) as pool:
            responses = list(pool.map(
                lambda i: client.get(f"/meal-images/{i}", headers=headers), ids))
    assert [r.status_code for r in responses] == [200] * PARALLEL
    assert all(r.content == JPEG for r in responses)
    assert all(r.headers["cache-control"] == "private, max-age=2592000, immutable"
               for r in responses)
    # Lúc cả 20 request cùng chờ Storage, không request nào giữ kết nối DB.
    assert len(storage.checked_out) == PARALLEL
    assert storage.checked_out[0] == 0


def test_parallel_status_requests_all_200__AC1(db, make, auth, app_with):
    user = make.user()
    ids = ready_images(db, 3)
    with TestClient(app_with()) as client:
        headers = auth(user)
        query = "&".join(f"ids={i}" for i in ids)
        with ThreadPoolExecutor(PARALLEL) as pool:
            responses = list(pool.map(
                lambda _: client.get(f"/meal-images?{query}", headers=headers),
                range(PARALLEL)))
    assert [r.status_code for r in responses] == [200] * PARALLEL
    items = responses[0].json()["items"]
    assert [(i["image_id"], i["status"], i["attribution"]["provider"]) for i in items] == [
        (i, "ready", "pixabay") for i in ids]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-jwt"}])
def test_missing_or_invalid_token_401__AC2(db, app_with, headers):
    image_id = ready_images(db, 1)[0]
    with TestClient(app_with()) as client:
        assert client.get(f"/meal-images/{image_id}", headers=headers).status_code == 401
        assert client.get(f"/meal-images?ids={image_id}", headers=headers).status_code == 401


def test_unknown_image_404__AC2(make, auth, app_with):
    user = make.user()
    with TestClient(app_with()) as client:
        r = client.get("/meal-images/2147483000", headers=auth(user))
    assert r.status_code == 404
    assert r.json() == {"detail": "meal_image_not_found"}
    assert r.headers["cache-control"] == "no-store"


class BrokenStore:
    """Lỗi DB khi đọc dòng ảnh, sau khi xác thực (đọc DB thật) đã thành công."""

    def states(self, uow, ids):
        raise OperationalError("SELECT meal_images", {}, Exception("connection lost"))


def test_db_failure_503__AC2(make, auth, app_with):
    user = make.user()
    with TestClient(app_with(store=BrokenStore())) as client:
        for url in ("/meal-images/1", "/meal-images?ids=1"):
            r = client.get(url, headers=auth(user))
            assert r.status_code == 503, url
            assert r.json() == {"detail": "service_unavailable"}
            assert r.headers["cache-control"] == "no-store"
