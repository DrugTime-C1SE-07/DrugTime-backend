"""GET /meal-images và GET /meal-images/{image_id} (task 5.11: AC7, AC8).

Không DB, không Storage thật.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from drugtime.main import create_app
from drugtime.modules.ai_meal.adapters.inbound import images_http
from drugtime.modules.ai_meal.application.ports import ImageState
from drugtime.modules.ai_meal.domain.errors import StorageUnavailable
from drugtime.modules.identity import api as identity

MOD = "drugtime.modules.ai_meal.adapters.inbound.images_http"
READY = ImageState(42, "ready", "42.webp", "image/webp", "Nguyễn Văn A",
                   "https://pixabay.com/users/nguyen_van_a-222/", "https://pixabay.com/photos/example-42/")
STATES = {42: READY, 43: ImageState(43, "pending"), 44: ImageState(44, "failed")}


class Store:
    def __init__(self, states=STATES, fail=False):
        self.map, self.fail, self.asked = states, fail, []

    def states(self, uow, ids):
        self.asked.append(list(ids))
        if self.fail:
            raise OperationalError("SELECT", {}, Exception("down"))
        return {i: self.map[i] for i in ids if i in self.map}


class Storage:
    def __init__(self, fail=False):
        self.fail, self.paths = fail, []

    def download(self, path):
        self.paths.append(path)
        if self.fail:
            raise StorageUnavailable("status_500")
        return b"RIFF....WEBP"


@contextmanager
def _uow():
    yield MagicMock()


def _client(store=None, storage=None, user=True):
    app = create_app()
    app.dependency_overrides[images_http.get_image_store] = lambda: store or Store()
    app.dependency_overrides[images_http.get_image_storage] = lambda: storage or Storage()
    if user:
        app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(
            id=uuid4(), is_admin=False)
    return TestClient(app, raise_server_exceptions=False)


def _get(client, url):
    with patch(f"{MOD}.unit_of_work", _uow):
        return client.get(url)


def test_list_states_in_query_order_skipping_unknown__AC7():
    store = Store()
    r = _get(_client(store), "/meal-images?ids=44&ids=999&ids=42&ids=43")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"items": [
        {"image_id": 44, "status": "failed", "url": None, "attribution": None},
        {"image_id": 42, "status": "ready", "url": "/meal-images/42",
         "attribution": {"provider": "pixabay", "photographer_name": "Nguyễn Văn A",
                         "photographer_url": "https://pixabay.com/users/nguyen_van_a-222/",
                         "source_url": "https://pixabay.com/photos/example-42/"}},
        {"image_id": 43, "status": "pending", "url": None, "attribution": None},
    ]}
    assert store.asked == [[44, 999, 42, 43]]


@pytest.mark.parametrize(
    "query",
    ["", "?ids=0", "?ids=abc", "?ids=1&ids=1", "?" + "&".join(f"ids={i}" for i in range(1, 22))],
)
def test_list_invalid_ids_422(query):
    store = Store()
    r = _get(_client(store), f"/meal-images{query}")
    assert r.status_code == 422 and store.asked == []


def test_list_db_failure_503():
    r = _get(_client(Store(fail=True)), "/meal-images?ids=1")
    assert (r.status_code, r.json()) == (503, {"detail": "service_unavailable"})


@pytest.mark.parametrize("url", ["/meal-images?ids=1", "/meal-images/42"])
def test_requires_session_401(url):
    r = _client(user=False).get(url)
    assert r.status_code == 401


def test_content_ready_returns_bytes_with_immutable_cache__AC7():
    storage = Storage()
    r = _get(_client(storage=storage), "/meal-images/42")
    assert r.status_code == 200 and r.content == b"RIFF....WEBP"
    assert r.headers["content-type"] == "image/webp"
    assert r.headers["cache-control"] == "private, max-age=2592000, immutable"
    assert storage.paths == ["42.webp"]


@pytest.mark.parametrize("image_id", [43, 44, 999])
def test_content_not_ready_or_missing_404__AC8(image_id):
    storage = Storage()
    r = _get(_client(storage=storage), f"/meal-images/{image_id}")
    assert (r.status_code, r.json()) == (404, {"detail": "meal_image_not_found"})
    assert r.headers["cache-control"] == "no-store" and storage.paths == []


def test_content_storage_failure_503():
    r = _get(_client(storage=Storage(fail=True)), "/meal-images/42")
    assert (r.status_code, r.json()) == (503, {"detail": "service_unavailable"})


@pytest.mark.parametrize("image_id", ["0", "abc"])
def test_content_bad_id_422(image_id):
    assert _get(_client(), f"/meal-images/{image_id}").status_code == 422
