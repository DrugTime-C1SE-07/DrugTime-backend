"""Ảnh minh họa món với Postgres thật (task 5.11: AC7, AC8).

Kho ảnh (Pexels) và kho lưu trữ (Supabase Storage) là bản giả; hàng đợi job là bản ghi lại.
Worker chạy use case `fetch_image` bằng kết nối `worker_role` thật để kiểm grant.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_meal_suggestions_api import (
    BODY,
    FakeLlm,
    create_patient,
    disable_real_llm,
    meal,
    output,
    suggest,
)

from drugtime.modules.ai_meal.adapters.inbound import http as meal_http
from drugtime.modules.ai_meal.adapters.inbound import images_http
from drugtime.modules.ai_meal.adapters.inbound.http import get_meal_suggester
from drugtime.modules.ai_meal.adapters.outbound.sql_meal_images import SqlMealImages
from drugtime.modules.ai_meal.application.fetch_image import fetch_image
from drugtime.modules.ai_meal.application.ports import FoundImage
from drugtime.modules.ai_meal.domain.errors import ImageSearchFailed
from drugtime.shared.config import get_settings

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture(autouse=True)
def _images_on(monkeypatch):
    disable_real_llm(monkeypatch)  # tắt LLM thật và ảnh theo .env
    monkeypatch.setenv("AI_MEAL_IMAGE_ENABLED", "true")  # bật ảnh, nhưng chỉ với bản giả
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class Queue:
    def __init__(self):
        self.sent = []

    def enqueue(self, image_id):
        self.sent.append(image_id)


class Storage:
    def __init__(self):
        self.files = {}

    def upload(self, path, content, content_type):
        self.files[path] = (content, content_type)

    def download(self, path):
        return self.files[path][0]


class Search:
    def __init__(self, fail=None):
        self.fail, self.queries = fail, []

    def find(self, query):
        self.queries.append(query)
        if self.fail:
            raise ImageSearchFailed(self.fail)
        return FoundImage(JPEG, "image/jpeg", "111", "Nguyễn Văn A",
                          "https://www.pexels.com/@a", "https://www.pexels.com/photo/111/")


@pytest.fixture
def env(client):
    queue, storage = Queue(), Storage()
    dish = f"Canh bí {uuid4().hex[:8]}"
    llm = FakeLlm(raw=output(meal(dish, image_query=f"winter melon soup {dish[-8:]}")))
    client.app.dependency_overrides[get_meal_suggester] = lambda: llm
    client.app.dependency_overrides[meal_http.get_image_queue] = lambda: queue
    client.app.dependency_overrides[images_http.get_image_storage] = lambda: storage
    return SimpleNamespace(queue=queue, storage=storage, dish=dish, llm=llm)


@pytest.fixture
def patient(client, db, make, auth, admin_auth, scheduled_body):
    return create_patient(client, db, make, auth, admin_auth, scheduled_body)


def worker_uow(role_engines):
    @contextmanager
    def factory():
        with role_engines["worker_role"].begin() as conn:
            yield SimpleNamespace(connection=conn)

    return factory


def image_row(db, image_id):
    return dict(db.execute(text("SELECT * FROM meal_images WHERE id = :i"),
                           {"i": image_id}).one()._mapping)


def test_pending_image_one_job_per_dish_then_worker_ready__AC7(
    client, db, make, auth, admin_auth, scheduled_body, role_engines, env, patient
):
    p = patient["id"]
    r = suggest(client, auth, p, p)
    assert r.status_code == 200, r.text
    image = r.json()["suggestions"][0]["image"]
    assert image["status"] == "pending" and image["url"] is None and image["attribution"] is None
    image_id = image["image_id"]
    assert env.queue.sent == [image_id]

    # Người bệnh khác, cùng món: dùng lại dòng ảnh, không tạo job thứ hai.
    other = create_patient(client, db, make, auth, admin_auth, scheduled_body)["id"]
    r2 = suggest(client, auth, other, other)
    assert r2.json()["suggestions"][0]["image"]["image_id"] == image_id
    assert env.queue.sent == [image_id]
    assert db.execute(text("SELECT count(*) FROM meal_images WHERE id = :i"),
                      {"i": image_id}).scalar_one() == 1

    # Worker (worker_role thật) tìm ảnh giả, lưu Storage giả, ghi ready.
    search = Search()
    result = fetch_image(image_id, uow_factory=worker_uow(role_engines),
                         records=SqlMealImages(), search=search, storage=env.storage)
    assert result == "ready"
    assert search.queries == [f"winter melon soup {env.dish[-8:]}"]  # chỉ cụm từ mô tả món
    row = image_row(db, image_id)
    assert (row["status"], row["storage_path"], row["content_type"], row["size_bytes"]) == (
        "ready", f"{image_id}.jpg", "image/jpeg", len(JPEG))
    assert (row["provider"], row["photographer_name"]) == ("pexels", "Nguyễn Văn A")

    # App hỏi trạng thái rồi tải ảnh qua Backend API.
    s = client.get(f"/meal-images?ids={image_id}&ids=999999999", headers=auth(p))
    assert s.status_code == 200 and s.headers["cache-control"] == "no-store"
    assert s.json() == {"items": [{
        "image_id": image_id, "status": "ready", "url": f"/meal-images/{image_id}",
        "attribution": {"provider": "pexels", "photographer_name": "Nguyễn Văn A",
                        "photographer_url": "https://www.pexels.com/@a",
                        "source_url": "https://www.pexels.com/photo/111/"}}]}
    c = client.get(f"/meal-images/{image_id}", headers=auth(p))
    assert c.status_code == 200 and c.content == JPEG
    assert c.headers["content-type"] == "image/jpeg"
    assert c.headers["cache-control"] == "private, max-age=2592000, immutable"

    # Món đã ready: gợi ý sau trả ảnh ready ngay, không đẩy job.
    r3 = suggest(client, auth, p, p)
    assert r3.json()["suggestions"][0]["image"]["status"] == "ready"
    assert env.queue.sent == [image_id]


@pytest.mark.parametrize("reason", ["no_result", "rate_limited", "upstream", "timeout",
                                    "not_image", "too_large"])
def test_provider_failure_marks_failed_no_file__AC8(
    client, db, auth, role_engines, env, patient, reason
):
    p = patient["id"]
    image_id = suggest(client, auth, p, p).json()["suggestions"][0]["image"]["image_id"]
    result = fetch_image(image_id, uow_factory=worker_uow(role_engines),
                         records=SqlMealImages(), search=Search(fail=reason),
                         storage=env.storage)
    assert result == f"failed:{reason}"
    assert image_row(db, image_id)["status"] == "failed" and env.storage.files == {}
    s = client.get(f"/meal-images?ids={image_id}", headers=auth(p)).json()["items"][0]
    assert (s["status"], s["url"]) == ("failed", None)
    assert client.get(f"/meal-images/{image_id}", headers=auth(p)).status_code == 404
    # Gợi ý vẫn trả bình thường, ảnh failed (app dùng ảnh mặc định), không đẩy job lại ngay.
    again = suggest(client, auth, p, p)
    assert again.status_code == 200
    assert again.json()["suggestions"][0]["image"]["status"] == "failed"
    assert env.queue.sent == [image_id]


def test_stale_pending_reads_failed_and_retry_after_24h__AC8(client, db, auth, env, patient):
    p = patient["id"]
    image_id = suggest(client, auth, p, p).json()["suggestions"][0]["image"]["image_id"]
    db.execute(text("UPDATE meal_images SET updated_at = now() - interval '3 minutes' "
                    "WHERE id = :i"), {"i": image_id})
    s = client.get(f"/meal-images?ids={image_id}", headers=auth(p)).json()["items"][0]
    assert s["status"] == "failed"  # pending quá 2 phút

    db.execute(text("UPDATE meal_images SET status = 'failed', "
                    "updated_at = now() - interval '25 hours' WHERE id = :i"), {"i": image_id})
    r = suggest(client, auth, p, p)
    assert r.json()["suggestions"][0]["image"] == {
        "image_id": image_id, "status": "pending", "url": None, "attribution": None}
    assert env.queue.sent == [image_id, image_id]


def test_images_disabled_no_row_no_job__AC8(client, db, auth, env, patient, monkeypatch):
    monkeypatch.setenv("AI_MEAL_IMAGE_ENABLED", "false")
    get_settings.cache_clear()
    p = patient["id"]
    before = db.execute(text("SELECT count(*) FROM meal_images")).scalar_one()
    r = suggest(client, auth, p, p)
    assert r.status_code == 200 and r.json()["suggestions"][0]["image"] is None
    assert env.queue.sent == []
    assert db.execute(text("SELECT count(*) FROM meal_images")).scalar_one() == before


def test_image_endpoints_require_session(client):
    assert client.get("/meal-images?ids=1").status_code == 401
    assert client.get("/meal-images/1").status_code == 401


def test_response_and_storage_never_carry_image_query__AC9(client, db, auth, env, patient):
    p = patient["id"]
    r = suggest(client, auth, p, p, body=BODY)
    assert "image_query" not in r.text and "winter melon soup" not in r.text
    content = db.execute(text("SELECT suggestion_content::text FROM meal_suggestions "
                              "WHERE user_id = :u"), {"u": p}).scalar_one()
    assert "image_query" not in content and "winter melon soup" not in content
