"""Unit test HTTP POST /patients/{patient_id}/meal-suggestions (task 4.26; 5.11).

AC7, AC10, AC12, AC12b, AC17, AC18 ở mức HTTP, không DB thật, không gọi Claude.
"""

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from drugtime.main import create_app
from drugtime.modules.ai_meal.adapters.inbound import http
from drugtime.modules.ai_meal.adapters.outbound.claude_suggester import ClaudeMealSuggester
from drugtime.modules.ai_meal.application import suggest_meals as uc
from drugtime.modules.ai_meal.application.ports import FoodCheck, FoodWarningView
from drugtime.modules.ai_meal.domain.errors import LlmInvalidOutput, LlmUnavailable
from drugtime.modules.ai_meal.domain.model import MEAL_DISCLAIMER
from drugtime.modules.identity import api as identity
from drugtime.shared.config import Settings
from drugtime.shared.db import get_uow
from drugtime.shared.errors import Forbidden

HTTP = "drugtime.modules.ai_meal.adapters.inbound.http"
PATIENT = uuid4()
T0 = datetime(2026, 11, 16, 4, 30, tzinfo=UTC)
SENSITIVE = ("Tăng huyết áp", "Losartan", "Cozaar", "Tôm", "Chuối", "Cơm gà luộc")
WARNING = FoodWarningView(81, 930, 620, "Losartan", "Chuối", 2, "Tăng kali máu", "Dược thư")
CHECK = FoodCheck("co_tuong_tac", (WARNING,), ("Losartan",), ("Cozaar",))

GOOD = json.dumps({
    "meal_type": "trua",
    "suggestions": [{
        "name": "Cơm gà luộc", "dish_type": "com", "image_query": "boiled chicken rice",
        "tags": ["Ít muối"], "kcal_estimate": 500, "cook_minutes": 30,
        "benefits": [{"text": "Ít muối, tốt cho huyết áp", "related_to": "condition:1"},
                     {"text": "Tốt cho tim", "related_to": "general"}],
        "ingredients": [{"name": "Gà", "amount": "120 g", "group": "chinh",
                         "use_sparingly": False}],
        "disclaimer": "LLM disclaimer bị bỏ",
    }],
}, ensure_ascii=False)

BODY = {
    "meal_type": "trua",
    "allergies": {"none": False, "items": ["Tôm"]},
    "dietary_restrictions": {"none": True, "items": []},
    "preferences": ["Ít cay"],
}


class FakeSuggester:
    def __init__(self, raw=GOOD, error=None):
        self.raw, self.error, self.calls = raw, error, 0

    def suggest(self, prompt):
        self.calls += 1
        if self.error:
            raise self.error
        return self.raw


class Uow:
    """Ghi lại transaction kết thúc bằng commit hay rollback."""

    def __init__(self):
        self.outcome = None

    @contextmanager
    def __call__(self):
        try:
            yield MagicMock()
        except BaseException:
            self.outcome = "rollback"
            raise
        self.outcome = "commit"


class Store:
    def __init__(self, previous=None, used=0):
        self.rows, self.previous, self.used = [], previous, used

    def insert(self, uow, user_id, content, previous_suggestion_id=None):
        self.rows.append(content)
        return 3051, T0

    def find_previous(self, uow, suggestion_id, user_id):
        return self.previous

    def count_refreshes(self, uow, user_id, since, *, lock):
        return self.used


class Queue:
    def __init__(self, fail=False):
        self.fail, self.sent = fail, []

    def enqueue(self, image_id):
        if self.fail:
            raise ConnectionError("broker down amqp://guest:secret@host")
        self.sent.append(image_id)


def _user(patient=PATIENT):
    return identity.CurrentUser(id=patient, is_admin=False)


def _fake_get_uow():
    yield MagicMock()


def _client(suggester, user=True, images=None, queue=None, limit=2):
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_get_uow
    app.dependency_overrides[http.get_meal_suggester] = lambda: suggester
    app.dependency_overrides[http.get_meal_images] = lambda: images
    app.dependency_overrides[http.get_image_queue] = lambda: queue or Queue()
    app.dependency_overrides[http.get_refresh_limit] = lambda: limit
    if user:
        app.dependency_overrides[identity.current_user] = _user
    return TestClient(app, raise_server_exceptions=False)


def _post(client, body=BODY, *, authorize=None, store=None, uow=None):
    uow = uow or Uow()
    store = store or Store()
    food = MagicMock()
    food.return_value.read.return_value = CHECK
    conditions = MagicMock()
    conditions.return_value.names.return_value = ["Tăng huyết áp"]
    with patch(f"{HTTP}.unit_of_work", uow), patch(f"{HTTP}.InteractionFoodCheck", food), patch(
        f"{HTTP}.MedicationConditions", conditions
    ), patch(f"{HTTP}.SqlMealSuggestions", return_value=store), patch.object(
        uc.access, "authorize", side_effect=authorize
    ):
        r = client.post(f"/patients/{PATIENT}/meal-suggestions", json=body)
    return r, uow, store


def test_401_without_token():
    r = _client(FakeSuggester(), user=False).post(
        f"/patients/{PATIENT}/meal-suggestions", json=BODY)
    assert r.status_code == 401


def test_success_payload_with_backend_disclaimer__AC7_AC11():
    sug = FakeSuggester()
    r, uow, store = _post(_client(sug))
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["suggestion_id"] == 3051 and data["meal_type"] == "trua"
    assert data["created_at"] == "2026-11-16T11:30:00+07:00"
    assert data["disclaimer"] == MEAL_DISCLAIMER and "LLM disclaimer" not in r.text
    meal, = data["suggestions"]
    assert meal["benefits"][0]["related_to"] == {"type": "condition", "label": "Tăng huyết áp"}
    assert meal["benefits"][1]["related_to"] == {"type": "general", "label": None}
    assert set(meal) == {"name", "dish_type", "is_new", "tags", "kcal_estimate", "cook_minutes",
                         "image", "benefits", "ingredients"}
    assert (meal["dish_type"], meal["is_new"], meal["image"]) == ("com", True, None)
    assert data["refreshes_remaining"] == 2 and "image_query" not in r.text
    assert data["food_check"] == {
        "status": "co_tuong_tac",
        "warnings": [{"rule_id": 81, "version_id": 930,
                      "ingredient": {"id": 620, "standard_name": "Losartan"},
                      "food_to_avoid": "Chuối", "severity_level": 2,
                      "reason": "Tăng kali máu", "source": "Dược thư"}],
    }
    assert uow.outcome == "commit" and len(store.rows) == 1 and sug.calls == 1


@pytest.mark.parametrize(
    "error,status,detail",
    [
        (LlmUnavailable("timeout"), 503, "llm_unavailable"),
        (LlmUnavailable("rate_limited"), 503, "llm_unavailable"),
        (LlmInvalidOutput("refusal"), 502, "llm_invalid_output"),
    ],
)
def test_llm_errors_mapped_with_no_store_and_commit__AC12(error, status, detail):
    r, uow, store = _post(_client(FakeSuggester(error=error)))
    assert (r.status_code, r.json()) == (status, {"detail": detail})
    assert r.headers["cache-control"] == "no-store"
    # Dòng access_logs `allowed` vẫn commit; không có meal_suggestions.
    assert uow.outcome == "commit" and store.rows == []


def test_invalid_output_502__AC12():
    r, uow, store = _post(_client(FakeSuggester(raw="xin lỗi")))
    assert (r.status_code, r.json()) == (502, {"detail": "llm_invalid_output"})
    assert store.rows == []


def test_llm_disabled_503__AC10():
    r, uow, store = _post(_client(None))
    assert (r.status_code, r.json()) == (503, {"detail": "llm_disabled"})
    assert r.headers["cache-control"] == "no-store" and store.rows == []


def test_forbidden_403_no_llm():
    sug = FakeSuggester()
    r, uow, _ = _post(_client(sug), authorize=Forbidden("khong_co_quyen"))
    assert (r.status_code, r.json()) == (403, {"detail": "khong_co_quyen"})
    assert sug.calls == 0


def _db_error():
    return OperationalError(
        "INSERT INTO access_logs ...", {"p": "Tăng huyết áp"}, Exception("down")
    )


def _unavailable(r):
    assert (r.status_code, r.json()) == (503, {"detail": "service_unavailable"})
    assert r.headers["cache-control"] == "no-store"
    assert "Cơm" not in r.text and "Tăng huyết áp" not in r.text and "INSERT" not in r.text


def test_allowed_log_failure_returns_503_no_data__AC17_M2():
    sug = FakeSuggester()
    r, uow, store = _post(_client(sug), authorize=_db_error())
    _unavailable(r)
    assert uow.outcome == "rollback" and sug.calls == 0 and store.rows == []


def test_store_failure_returns_503_and_rolls_back__AC17_M2():
    class Broken(Store):
        def insert(self, uow, user_id, content, previous_suggestion_id=None):
            raise _db_error()

    r, uow, _ = _post(_client(FakeSuggester()), store=Broken())
    _unavailable(r)
    assert uow.outcome == "rollback"


def test_commit_failure_returns_503__AC17_M2():
    class FailingCommit(Uow):
        @contextmanager
        def __call__(self):
            yield MagicMock()
            self.outcome = "commit_failed"
            raise _db_error()

    uow = FailingCommit()
    r, _, _ = _post(_client(FakeSuggester()), uow=uow)
    _unavailable(r)
    assert uow.outcome == "commit_failed"


def test_non_database_error_still_500_without_data__AC17():
    sug = FakeSuggester()
    r, uow, store = _post(_client(sug), authorize=RuntimeError("unexpected"))
    assert r.status_code == 500 and "Cơm" not in r.text
    assert uow.outcome == "rollback" and sug.calls == 0 and store.rows == []
    assert uow.outcome == "rollback"


INVALID = {
    "missing allergies": {k: v for k, v in BODY.items() if k != "allergies"},
    "none false empty": {**BODY, "allergies": {"none": False, "items": []}},
    "none true with items": {**BODY, "dietary_restrictions": {"none": True, "items": ["Chay"]}},
    "meal_type khuya": {**BODY, "meal_type": "khuya"},
    "unknown field": {**BODY, "patient_name": "A"},
    "item 41": {**BODY, "allergies": {"none": False, "items": ["x" * 41]}},
    "blank item": {**BODY, "allergies": {"none": False, "items": ["  "]}},
    "11 allergies": {**BODY, "allergies": {"none": False, "items": [f"a{i}" for i in range(11)]}},
    "duplicate allergies": {**BODY, "allergies": {"none": False, "items": ["Tôm", "tôm"]}},
    "6 preferences": {**BODY, "preferences": [f"p{i}" for i in range(6)]},
}


@pytest.mark.parametrize("body", INVALID.values(), ids=INVALID.keys())
def test_invalid_body_422_no_llm__AC12b(body):
    sug = FakeSuggester()
    r, uow, store = _post(_client(sug), body=body)
    assert r.status_code == 422
    assert sug.calls == 0 and store.rows == [] and uow.outcome is None


def test_bad_patient_id_422():
    r = _client(FakeSuggester()).post("/patients/abc/meal-suggestions", json=BODY)
    assert r.status_code == 422


def test_no_health_data_in_logs__AC18(caplog):
    caplog.set_level(logging.DEBUG)
    for sug in (FakeSuggester(), FakeSuggester(error=LlmUnavailable("upstream")),
                FakeSuggester(raw='{"meal_type":"trua","suggestions":[]}')):
        _post(_client(sug))
    assert "llm_failure" in caplog.text  # có log mã lỗi
    for text in SENSITIVE:
        assert text not in caplog.text


def test_get_meal_suggester_respects_flag_and_key__AC10():
    http._claude.cache_clear()
    cases = [
        (dict(ai_meal_llm_enabled=False, llm_api_key="sk-ant-x"), None),
        (dict(ai_meal_llm_enabled=True, llm_api_key=""), None),
    ]
    for values, expected in cases:
        with patch(f"{HTTP}.get_settings", return_value=Settings(_env_file=None, **values)):
            assert http.get_meal_suggester() is expected
    on = Settings(_env_file=None, ai_meal_llm_enabled=True, llm_api_key="sk-ant-x",
                  llm_timeout_seconds=8.0)
    with patch(f"{HTTP}.get_settings", return_value=on):
        suggester = http.get_meal_suggester()
    assert isinstance(suggester, ClaudeMealSuggester)
    assert suggester._client.max_retries == 0 and suggester._client.timeout == 8.0
    http._claude.cache_clear()


# --- Task 5.11 -----------------------------------------------------------------------------

from drugtime.modules.ai_meal.application.ports import (  # noqa: E402
    ImageReservation,
    ImageState,
)

PREVIOUS = {"meal_type": "trua", "suggestions": []}


def test_previous_not_found_422_string_detail_commits_allowed_log__AC16():
    sug = FakeSuggester()
    r, uow, store = _post(_client(sug), body={**BODY, "previous_suggestion_id": 77},
                          store=Store(previous=None))
    assert (r.status_code, r.json()) == (422, {"detail": "previous_suggestion_not_found"})
    assert r.headers["cache-control"] == "no-store"
    assert sug.calls == 0 and store.rows == [] and uow.outcome == "commit"


def test_refresh_limit_429_with_retry_after__AC27():
    sug = FakeSuggester()
    r, uow, store = _post(_client(sug), body={**BODY, "previous_suggestion_id": 77},
                          store=Store(previous=PREVIOUS, used=2))
    assert (r.status_code, r.json()) == (429, {"detail": "refresh_limit_reached"})
    assert r.headers["cache-control"] == "no-store"
    assert 1 <= int(r.headers["retry-after"]) <= 86400
    assert sug.calls == 0 and store.rows == []


def test_refresh_success_reports_remaining__AC27():
    r, _, _ = _post(_client(FakeSuggester()), body={**BODY, "previous_suggestion_id": 77},
                    store=Store(previous=PREVIOUS, used=1))
    assert r.status_code == 200 and r.json()["refreshes_remaining"] == 0


@pytest.mark.parametrize("value", [None, 0, "77", 1.5])
def test_bad_previous_suggestion_id_422__AC16(value):
    sug = FakeSuggester()
    r, _, _ = _post(_client(sug), body={**BODY, "previous_suggestion_id": value})
    assert r.status_code == 422 and sug.calls == 0


class Images:
    def __init__(self, state):
        self.state = state

    def reserve(self, uow, dish_key, query):
        state = self.state
        return ImageReservation(state.image_id, state.status, state.status == "pending")

    def states(self, uow, ids):
        return {self.state.image_id: self.state}


READY = ImageState(42, "ready", "42.jpg", "image/jpeg", "Nguyễn Văn A",
                   "https://www.pexels.com/@a", "https://www.pexels.com/photo/42/")


def test_ready_image_payload_and_no_enqueue__AC7():
    queue = Queue()
    r, _, _ = _post(_client(FakeSuggester(), images=Images(READY), queue=queue))
    image = r.json()["suggestions"][0]["image"]
    assert image == {"image_id": 42, "status": "ready", "url": "/meal-images/42",
                     "attribution": {"provider": "pexels", "photographer_name": "Nguyễn Văn A",
                                     "photographer_url": "https://www.pexels.com/@a",
                                     "source_url": "https://www.pexels.com/photo/42/"}}
    assert queue.sent == []


def test_pending_image_enqueued_after_commit__AC7():
    queue = Queue()
    r, uow, _ = _post(_client(FakeSuggester(), images=Images(ImageState(5, "pending")),
                              queue=queue))
    assert r.json()["suggestions"][0]["image"] == {
        "image_id": 5, "status": "pending", "url": None, "attribution": None}
    assert queue.sent == [5] and uow.outcome == "commit"


def test_no_enqueue_when_commit_fails__AC7():
    class FailingCommit(Uow):
        @contextmanager
        def __call__(self):
            yield MagicMock()
            raise _db_error()

    queue = Queue()
    r, _, _ = _post(_client(FakeSuggester(), images=Images(ImageState(5, "pending")),
                            queue=queue), uow=FailingCommit())
    assert r.status_code == 503 and queue.sent == []


def test_enqueue_failure_still_200_and_logs_no_secret__AC7(caplog):
    caplog.set_level(logging.DEBUG)
    r, _, _ = _post(_client(FakeSuggester(), images=Images(ImageState(5, "pending")),
                            queue=Queue(fail=True)))
    assert r.status_code == 200
    assert "image_enqueue_failed" in caplog.text and "secret" not in caplog.text


def test_get_meal_images_follows_flag__AC8():
    with patch(f"{HTTP}.get_settings", return_value=Settings(_env_file=None)):
        assert http.get_meal_images() is None
    on = Settings(_env_file=None, ai_meal_image_enabled=True)
    with patch(f"{HTTP}.get_settings", return_value=on):
        assert http.get_meal_images() is not None
