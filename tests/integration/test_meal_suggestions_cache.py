"""Cache CD10 cho gợi ý bữa ăn với Postgres và Redis thật (task 5.09).

AC3, AC4, AC5, AC6, AC8, AC9, AC13. LLM giả qua dependency override. Cache là `RedisMealCache`
thật trên Redis local (`TEST_REDIS_URL`, mặc định DB 15), bọc `SpyCache` để đếm lệnh get/put.
Mỗi test chỉ xóa key `meal_cache:*` của DB đó, trước và sau khi chạy.
"""

import logging
import os
from uuid import uuid4

import pytest
from redis import Redis, RedisError
from sqlalchemy import text
from test_meal_suggestions_api import (
    BODY,
    FakeLlm,
    add_med,
    add_rule,
    disable_real_llm,
    log,
    meal,
    meal_rows,
    output,
    suggest,
)

from drugtime.modules.ai_meal.adapters.inbound.http import get_meal_cache, get_meal_suggester
from drugtime.modules.ai_meal.adapters.outbound.redis_meal_cache import (
    RedisMealCache,
    build_client,
)
from drugtime.shared.config import get_settings

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
TTL = 3600
HTTP_LOGGER = "drugtime.modules.ai_meal.adapters.inbound.http"


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    disable_real_llm(monkeypatch)
    yield
    get_settings.cache_clear()


def _clear(redis: Redis) -> None:
    for key in redis.scan_iter("meal_cache:*"):
        redis.delete(key)


@pytest.fixture
def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
    try:
        client.ping()
    except RedisError as exc:
        # Không skip: test tích hợp của 5.09 bắt buộc có Redis thật.
        pytest.fail(f"Redis local không chạy ở {REDIS_URL} ({type(exc).__name__})")
    _clear(client)
    yield client
    _clear(client)


class SpyCache:
    def __init__(self, inner):
        self.inner, self.gets, self.puts = inner, 0, 0

    def get(self, key):
        self.gets += 1
        return self.inner.get(key)

    def put(self, key, raw):
        self.puts += 1
        self.inner.put(key, raw)


@pytest.fixture
def cache(client, redis):
    spy = SpyCache(RedisMealCache(build_client(REDIS_URL, 1.0), TTL))
    client.app.dependency_overrides[get_meal_cache] = lambda: spy
    return spy


@pytest.fixture
def llm(client):
    fake = FakeLlm(raw=output(meal("Cơm gà luộc"), meal("Gỏi bưởi", ingredients=("Bưởi",))))
    client.app.dependency_overrides[get_meal_suggester] = lambda: fake
    return fake


def _condition(db, name):
    return db.execute(
        text("INSERT INTO conditions (name, medical_nature, data_role) "
             "VALUES (:n, 'benh_ly', 'dieu_chinh_thuoc_khac') RETURNING id"),
        {"n": name},
    ).scalar_one()


def _attach_condition(db, patient, condition_id):
    db.execute(text("INSERT INTO user_conditions (user_id, condition_id) VALUES (:u, :c)"),
               {"u": patient, "c": condition_id})


def _detach_condition(db, patient, condition_id):
    db.execute(text("DELETE FROM user_conditions WHERE user_id = :u AND condition_id = :c"),
               {"u": patient, "c": condition_id})


@pytest.fixture
def profile(client, db, make, admin_auth):
    """Tổ hợp thuốc + bệnh nền dùng chung cho nhiều người bệnh (cùng input → cùng key)."""
    iid = make.ingredient(name=f"Losartan {uuid4().hex[:6]}")
    rule = add_rule(client, admin_auth[1], iid)
    return {
        "ingredient_id": iid,
        "medication_id": make.medication_with([iid]),
        "condition_id": _condition(db, f"Tăng huyết áp {uuid4().hex[:6]}"),
        "rule": rule,
    }


@pytest.fixture
def new_patient(client, db, make, auth, scheduled_body, profile):
    def create():
        p = make.user(consents=("health_data", "ai_meal"))
        add_med(client, auth, p, scheduled_body, profile["medication_id"])
        _attach_condition(db, p, profile["condition_id"])
        return p

    return create


def _keys(redis):
    return list(redis.scan_iter("meal_cache:*"))


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def test_miss_calls_llm_stores_with_ttl_served_false__AC3(
    client, db, auth, llm, cache, redis, new_patient
):
    p = new_patient()
    _ok(suggest(client, auth, p, p))
    assert len(llm.prompts) == 1 and (cache.gets, cache.puts) == (1, 1)
    [key] = _keys(redis)
    assert 0 < redis.ttl(key) <= TTL
    assert str(p) not in key and str(p) not in redis.get(key)
    assert [row["served_from_cache"] for row in meal_rows(db, p)] == [False]


def test_hit_for_other_patient_same_input_no_llm__AC4(
    client, db, make, auth, llm, cache, redis, new_patient
):
    p1, p2 = new_patient(), new_patient()
    first = _ok(suggest(client, auth, p1, p1))
    second = _ok(suggest(client, auth, p2, p2))
    assert len(llm.prompts) == 1 and cache.puts == 1 and len(_keys(redis)) == 1
    assert second["disclaimer"] == first["disclaimer"]
    assert set(second) == set(first)
    assert [m["name"] for m in second["suggestions"]] == [m["name"] for m in first["suggestions"]]
    assert make.access_logs(p2) == [log(p2, "patient", "allowed")]
    assert [row["served_from_cache"] for row in meal_rows(db, p1)] == [False]
    assert [row["served_from_cache"] for row in meal_rows(db, p2)] == [True]


def test_same_patient_repeat_hits__AC4(client, db, auth, llm, cache, new_patient):
    p = new_patient()
    _ok(suggest(client, auth, p, p))
    _ok(suggest(client, auth, p, p))
    assert len(llm.prompts) == 1
    assert [row["served_from_cache"] for row in meal_rows(db, p)] == [False, True]


def test_condition_change_misses_then_revert_hits__AC5(
    client, db, auth, llm, cache, redis, new_patient
):
    p = new_patient()
    _ok(suggest(client, auth, p, p))
    extra = _condition(db, f"Gout {uuid4().hex[:6]}")
    _attach_condition(db, p, extra)
    _ok(suggest(client, auth, p, p))
    assert len(llm.prompts) == 2 and len(_keys(redis)) == 2  # key mới, entry cũ còn nguyên
    _detach_condition(db, p, extra)
    _ok(suggest(client, auth, p, p))
    assert len(llm.prompts) == 2
    assert [r["served_from_cache"] for r in meal_rows(db, p)] == [False, False, True]


def test_medication_added_misses__AC5(
    client, db, make, auth, scheduled_body, llm, cache, redis, new_patient
):
    p, same = new_patient(), new_patient()
    _ok(suggest(client, auth, p, p))
    other = make.ingredient(name=f"Metformin {uuid4().hex[:6]}")
    add_med(client, auth, p, scheduled_body, make.medication_with([other]))
    _ok(suggest(client, auth, p, p))
    assert len(llm.prompts) == 2 and len(_keys(redis)) == 2
    # Người bệnh chưa thêm thuốc vẫn dùng entry cũ.
    _ok(suggest(client, auth, same, same))
    assert len(llm.prompts) == 2
    assert [r["served_from_cache"] for r in meal_rows(db, same)] == [True]


def test_food_rule_change_misses_and_new_avoid_food_filtered__AC6(
    client, auth, admin_auth, llm, cache, redis, new_patient, profile
):
    p = new_patient()
    before = _ok(suggest(client, auth, p, p))
    assert "Gỏi bưởi" in [m["name"] for m in before["suggestions"]]
    add_rule(client, admin_auth[1], profile["ingredient_id"], food="Bưởi")
    after = _ok(suggest(client, auth, p, p))
    assert len(llm.prompts) == 2 and len(_keys(redis)) == 2
    assert [m["name"] for m in after["suggestions"]] == ["Cơm gà luộc"]


def test_redis_unreachable_still_200__AC8(client, db, auth, llm, monkeypatch, new_patient):
    monkeypatch.setenv("MEAL_CACHE_URL", "redis://127.0.0.1:1/0")  # cổng không có Redis
    get_settings.cache_clear()
    p = new_patient()
    r1 = suggest(client, auth, p, p)
    r2 = suggest(client, auth, p, p)
    assert (r1.status_code, r2.status_code) == (200, 200), r1.text
    assert len(llm.prompts) == 2  # không có cache → mỗi lần gọi LLM
    assert [row["served_from_cache"] for row in meal_rows(db, p)] == [False, False]


def _denied_caller(case, make, p):
    if case == "consent_revoked":
        make.revoke_consent(p, "ai_meal")
        return p, "patient", "consent_revoked"
    if case == "family_with_full_consent":
        make.consent(p, "family_sharing")
        family = make.user(consents=("health_data", "ai_meal"))
        make.link(p, family)
        return family, "family", "khong_co_quyen"
    if case == "admin":
        return make.user(admin=True), "admin", "khong_co_quyen"
    if case == "other_patient":
        return make.user(consents=("health_data", "ai_meal")), "khong_co_quyen", "khong_co_quyen"
    raise AssertionError(case)


@pytest.mark.parametrize(
    "case", ["consent_revoked", "family_with_full_consent", "admin", "other_patient"]
)
def test_denied_never_reads_cache_or_llm__AC9(
    client, db, make, auth, llm, cache, redis, new_patient, case
):
    warm, p = new_patient(), new_patient()
    _ok(suggest(client, auth, warm, warm))  # entry khớp đúng input của p đã có trong cache
    gets, prompts = cache.gets, len(llm.prompts)
    caller, role, reason = _denied_caller(case, make, p)
    r = suggest(client, auth, caller, p)
    assert (r.status_code, r.json()) == (403, {"detail": reason})
    assert cache.gets == gets and len(llm.prompts) == prompts
    assert make.access_logs(p) == [log(caller, role, "denied", reason)]
    assert meal_rows(db, p) == []


def test_refresh_bypasses_cache__AC10(client, db, auth, llm, cache, new_patient):
    p = new_patient()
    first = _ok(suggest(client, auth, p, p))
    gets, puts = cache.gets, cache.puts
    r = suggest(client, auth, p, p, body={**BODY, "previous_suggestion_id": first["suggestion_id"]})
    _ok(r)
    assert (cache.gets, cache.puts) == (gets, puts) and len(llm.prompts) == 2


def test_cache_events_logged__AC13(client, auth, llm, cache, redis, new_patient, caplog):
    caplog.set_level(logging.INFO, logger=HTTP_LOGGER)
    p1, p2 = new_patient(), new_patient()
    _ok(suggest(client, auth, p1, p1))
    _ok(suggest(client, auth, p2, p2))
    events = [r.getMessage() for r in caplog.records if "ai_meal cache" in r.getMessage()]
    assert events == ["ai_meal cache event=miss", "ai_meal cache event=hit"]
    [key] = _keys(redis)
    for leaked in (key, str(p1), str(p2), REDIS_URL):
        assert leaked not in caplog.text
