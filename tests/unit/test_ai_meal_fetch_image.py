"""Use case Worker fetch_image và Celery task (task 5.11: AC7, AC8)."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from drugtime.modules.ai_meal import tasks
from drugtime.modules.ai_meal.application.fetch_image import fetch_image, storage_path
from drugtime.modules.ai_meal.application.ports import FoundImage, PendingImage
from drugtime.modules.ai_meal.domain.errors import ImageSearchFailed, StorageUnavailable

FOUND = FoundImage(b"\xff\xd8\xffx", "image/jpeg", "111", "Nguyễn Văn A",
                   "https://www.pexels.com/@a", "https://www.pexels.com/photo/111/")


PENDING = PendingImage(42, "vietnamese sour fish soup")


class Records:
    def __init__(self, pending=PENDING):
        self.pending, self.events = pending, []

    def load_pending(self, uow, image_id):
        self.events.append(("load", image_id))
        return self.pending

    def mark_ready(self, uow, image_id, path, found):
        self.events.append(("ready", image_id, path, found))

    def mark_failed(self, uow, image_id):
        self.events.append(("failed", image_id))


class Search:
    def __init__(self, result):
        self.result, self.queries = result, []

    def find(self, query):
        self.queries.append(query)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Storage:
    def __init__(self, fail=False):
        self.fail, self.uploads = fail, []

    def upload(self, path, content, content_type):
        if self.fail:
            raise StorageUnavailable("status_500")
        self.uploads.append((path, content, content_type))


@contextmanager
def _uow():
    yield object()


def _run(records, search, storage):
    return fetch_image(42, uow_factory=_uow, records=records, search=search, storage=storage)


def test_success_uploads_and_marks_ready_with_attribution__AC7():
    records, search, storage = Records(), Search(FOUND), Storage()
    assert _run(records, search, storage) == "ready"
    assert search.queries == ["vietnamese sour fish soup"]
    assert storage.uploads == [("42.jpg", FOUND.content, "image/jpeg")]
    assert records.events[-1] == ("ready", 42, "42.jpg", FOUND)


@pytest.mark.parametrize("reason", ["no_result", "rate_limited", "upstream", "timeout",
                                    "not_image", "too_large"])
def test_search_failure_marks_failed_and_uploads_nothing__AC8(reason):
    records, storage = Records(), Storage()
    assert _run(records, Search(ImageSearchFailed(reason)), storage) == f"failed:{reason}"
    assert storage.uploads == [] and records.events[-1] == ("failed", 42)


def test_storage_failure_marks_failed__AC8():
    records = Records()
    assert _run(records, Search(FOUND), Storage(fail=True)) == "failed:status_500"
    assert records.events[-1] == ("failed", 42)


def test_not_pending_is_skipped():
    records, search = Records(pending=None), Search(FOUND)
    assert _run(records, search, Storage()) == "skipped"
    assert search.queries == []


@pytest.mark.parametrize(("ct", "ext"), [("image/jpeg", "jpg"), ("image/png", "png"),
                                         ("image/webp", "webp")])
def test_storage_path_by_type(ct, ext):
    assert storage_path(7, ct) == f"7.{ext}"


def test_task_disabled_does_not_call_provider__AC8(monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: type("S", (), {
        "ai_meal_image_enabled": False,
        "pexels_api_key": type("K", (), {"get_secret_value": lambda self: "k"})(),
    })())
    with patch.object(tasks, "fetch_image") as run:
        assert tasks.fetch_meal_image(42) == "disabled"
    run.assert_not_called()


def test_task_registered_with_expected_name():
    assert tasks.fetch_meal_image.name == "ai_meal.fetch_image"
