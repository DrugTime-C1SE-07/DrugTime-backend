"""Endpoint ảnh món không giữ kết nối DB khi tải ảnh từ Storage.

Task adhoc-20261120-meal-image-loading (AC1, AC2). Không dùng DB thật: `get_uow` và
`unit_of_work` được thay bằng bản giả có bộ đếm số unit of work đang mở. Xác thực đi qua
`identity.current_user` thật (JWT phiên ký bằng secret của test, `SqlUsers` giả).
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.ai_meal.adapters.inbound import images_http
from drugtime.modules.ai_meal.application.ports import ImageState
from drugtime.modules.identity.adapters.inbound import dependencies
from drugtime.modules.identity.application import sign_in
from drugtime.modules.identity.domain.user import SessionType, UserRecord
from drugtime.shared.config import get_settings
from drugtime.shared.db import get_uow

SESSION_SECRET = "session-secret-for-tests-0123456789abcdef"
READY = ImageState(42, "ready", "42.jpg", "image/jpeg", "nguyen_van_a",
                   "https://pixabay.com/users/nguyen_van_a-222/",
                   "https://pixabay.com/photos/example-42/")


class Counter:
    def __init__(self):
        self.open = 0
        self.peak = 0

    def enter(self):
        self.open += 1
        self.peak = max(self.peak, self.open)

    def exit(self):
        self.open -= 1


class Store:
    def __init__(self, counter):
        self.counter, self.open_seen = counter, []

    def states(self, uow, ids):
        self.open_seen.append(self.counter.open)
        return {i: READY for i in ids if i == 42}


class Storage:
    def __init__(self, counter):
        self.counter, self.open_during_download = counter, []

    def download(self, path):
        self.open_during_download.append(self.counter.open)
        return b"\xff\xd8\xff\xe0jpeg"


class _Users:
    def __init__(self, uow):
        pass

    def get(self, user_id):
        return UserRecord(user_id, is_admin=False, erased=False, profile_complete=True)


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("SESSION_JWT_SECRET", SESSION_SECRET)
    get_settings.cache_clear()
    monkeypatch.setattr(dependencies, "SqlUsers", _Users)
    yield
    get_settings.cache_clear()


@pytest.fixture
def env(monkeypatch):
    counter = Counter()

    @contextmanager
    def counted_uow():
        counter.enter()
        try:
            yield object()
        finally:
            counter.exit()

    def counted_get_uow():
        with counted_uow() as uow:
            yield uow

    monkeypatch.setattr(images_http, "unit_of_work", counted_uow)
    store, storage = Store(counter), Storage(counter)
    app = create_app()
    app.dependency_overrides[get_uow] = counted_get_uow
    app.dependency_overrides[images_http.get_image_store] = lambda: store
    app.dependency_overrides[images_http.get_image_storage] = lambda: storage
    client = TestClient(app, raise_server_exceptions=False)
    return client, counter, store, storage


def _auth():
    token = sign_in.issue_app_session(uuid4(), SessionType.MOBILE, datetime.now(UTC)).token
    return {"Authorization": f"Bearer {token}"}


def test_content_endpoint_holds_no_connection_during_storage__AC1(env):
    client, counter, _, storage = env
    r = client.get("/meal-images/42", headers=_auth())
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff\xe0jpeg"
    assert storage.open_during_download == [0]
    assert counter.peak == 1
    assert counter.open == 0


def test_status_endpoint_holds_at_most_one_connection__AC1(env):
    client, counter, store, _ = env
    r = client.get("/meal-images?ids=42", headers=_auth())
    assert r.status_code == 200
    assert r.json()["items"][0]["attribution"]["provider"] == "pixabay"
    assert store.open_seen == [1]
    assert counter.peak == 1
    assert counter.open == 0


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-jwt"},
                                     {"Authorization": "Basic abc"}])
@pytest.mark.parametrize("url", ["/meal-images/42", "/meal-images?ids=42"])
def test_missing_or_invalid_token_401__AC2(env, headers, url):
    client, counter, _, storage = env
    r = client.get(url, headers=headers)
    assert r.status_code == 401
    assert storage.open_during_download == []
    assert counter.open == 0
