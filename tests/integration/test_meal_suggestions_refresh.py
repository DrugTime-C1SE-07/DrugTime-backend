"""Gợi ý lại và giới hạn lượt với Postgres thật (task 5.11: AC14, AC15, AC16, AC27).

LLM giả qua dependency override; ảnh tắt; không gọi Anthropic hay Pexels.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_meal_suggestions_api import (
    BODY,
    FakeLlm,
    add_med,
    add_rule,
    create_patient,
    disable_real_llm,
    meal,
    output,
    suggest,
)

from drugtime.main import create_app
from drugtime.modules.ai_meal.adapters.inbound.http import get_meal_suggester
from drugtime.modules.ai_meal.domain.errors import LlmInvalidOutput
from drugtime.modules.ai_meal.domain.refresh import day_start_vn
from drugtime.shared.config import get_settings

OLD = ["Cơm gà luộc", "Canh chua cá", "Đậu hũ sốt cà", "Rau muống xào tỏi", "Trứng hấp",
       "Bí xanh luộc"]
NEW = ["Bún bò Huế ít cay", "Cơm gạo lứt thịt nạc", "Miến gà", "Cơm gà luộc"]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    disable_real_llm(monkeypatch)
    yield
    get_settings.cache_clear()


def first_output():
    return output(*(meal(n, ingredients=("Cá",) if "cá" in n else ("Gà",)) for n in OLD))


def refresh_output():
    return output(*(meal(n) for n in NEW))


class ScriptedLlm(FakeLlm):
    """Trả lần lượt từng output; hết thì lặp output cuối."""

    def __init__(self, *raws, error_on=None):
        super().__init__(raw=raws[0])
        self.raws, self.error_on = list(raws), error_on or set()

    def suggest(self, prompt):
        self.prompts.append(prompt)
        n = len(self.prompts)
        if n in self.error_on:
            raise LlmInvalidOutput("schema")
        raw = self.raws[min(n, len(self.raws)) - 1]
        # Trả đúng bữa được hỏi (parser từ chối output khác meal_type).
        return raw.replace('"meal_type": "trua"', f'"meal_type": "{prompt.meal_type.value}"')


def install(client, llm):
    client.app.dependency_overrides[get_meal_suggester] = lambda: llm
    return llm


def rows(db, p):
    return [dict(r._mapping) for r in db.execute(
        text("SELECT id, previous_suggestion_id, suggestion_content FROM meal_suggestions "
             "WHERE user_id = :u ORDER BY id"), {"u": p})]


@pytest.fixture
def patient(client, db, make, auth, admin_auth, scheduled_body):
    return create_patient(client, db, make, auth, admin_auth, scheduled_body)


def refresh(client, auth, p, previous_id, **body):
    return suggest(client, auth, p, p, body={**BODY, **body, "previous_suggestion_id": previous_id})


# --- AC14 ---------------------------------------------------------------------------------


def test_refresh_keeps_old_and_adds_new__AC14(client, db, auth, patient):
    p = patient["id"]
    llm = install(client, ScriptedLlm(first_output(), refresh_output()))
    g1 = suggest(client, auth, p, p)
    assert g1.status_code == 200, g1.text
    assert g1.json()["refreshes_remaining"] == 2
    g1_id = g1.json()["suggestion_id"]

    r = refresh(client, auth, p, g1_id)
    assert r.status_code == 200, r.text
    data = r.json()
    names = [s["name"] for s in data["suggestions"]]
    # 3 món mới đứng trước ("Cơm gà luộc" trùng món cũ bị loại); món chính cũ không còn;
    # món cũ giữ thứ tự gốc; tổng ≤ 6; "Canh chua cá" vẫn hợp lệ nên được giữ.
    assert names == ["Bún bò Huế ít cay", "Cơm gạo lứt thịt nạc", "Miến gà",
                     "Canh chua cá", "Đậu hũ sốt cà", "Rau muống xào tỏi"]
    assert [s["is_new"] for s in data["suggestions"]] == [True] * 3 + [False] * 3
    assert "Cơm gà luộc" not in names[3:]
    assert len(set(names)) == len(names) <= 6
    assert data["refreshes_remaining"] == 1

    # LLM nhận tên món cũ cần tránh + số món mới, không có định danh.
    prompt = llm.prompts[1]
    assert "đúng 3 món mới" in prompt.user
    for old in OLD:
        assert old in prompt.user
    assert str(p) not in prompt.user + prompt.system

    stored = rows(db, p)
    assert len(stored) == 2 and stored[1]["previous_suggestion_id"] == g1_id
    assert stored[1]["id"] == data["suggestion_id"]
    assert all("image_query" not in d for d in stored[1]["suggestion_content"]["suggestions"])


# --- AC15 ---------------------------------------------------------------------------------


def test_kept_dish_refiltered_by_new_food_rule__AC15(
    client, db, make, auth, admin_auth, scheduled_body, patient
):
    p = patient["id"]
    install(client, ScriptedLlm(first_output(), refresh_output()))
    g1_id = suggest(client, auth, p, p).json()["suggestion_id"]
    # Sau G1: P có thuốc mới với quy tắc "tránh cá".
    iid = make.ingredient(name=f"Hoạt chất mới {uuid4().hex[:6]}")
    add_rule(client, admin_auth[1], iid, food="Cá")
    add_med(client, auth, p, scheduled_body, make.medication_with([iid]))

    r = refresh(client, auth, p, g1_id)
    assert r.status_code == 200, r.text
    names = [s["name"] for s in r.json()["suggestions"]]
    assert "Canh chua cá" not in names
    # Bộ lọc của 4.26 so khớp không dấu nên "cà" cũng trùng từ khóa "cá" (loại thừa, phía an
    # toàn). Món cũ còn lại vẫn theo thứ tự gốc và đều là món của G1.
    kept = names[3:]
    assert kept == [n for n in OLD[1:] if n in kept]
    assert kept and all("cá" not in n.lower() for n in kept)


def test_kept_dish_refiltered_by_new_allergy__AC15(client, db, auth, patient):
    p = patient["id"]
    install(client, ScriptedLlm(first_output(), refresh_output()))
    g1_id = suggest(client, auth, p, p).json()["suggestion_id"]
    r = refresh(client, auth, p, g1_id, allergies={"none": False, "items": ["Cá"]})
    assert r.status_code == 200, r.text
    assert "Canh chua cá" not in [s["name"] for s in r.json()["suggestions"]]


# --- AC16 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["other_patient", "not_found", "other_meal"])
def test_previous_not_found_422_nothing_called_or_saved__AC16(
    client, db, make, auth, admin_auth, scheduled_body, patient, case
):
    p = patient["id"]
    llm = install(client, ScriptedLlm(first_output(), refresh_output()))
    if case == "other_patient":
        other = create_patient(client, db, make, auth, admin_auth, scheduled_body)["id"]
        previous_id = suggest(client, auth, other, other).json()["suggestion_id"]
    elif case == "not_found":
        previous_id = 2_000_000_000
    else:
        previous_id = suggest(client, auth, p, p,
                              body={**BODY, "meal_type": "toi"}).json()["suggestion_id"]
    before_calls, before_rows = len(llm.prompts), len(rows(db, p))

    r = refresh(client, auth, p, previous_id)
    assert (r.status_code, r.json()) == (422, {"detail": "previous_suggestion_not_found"})
    assert r.headers["cache-control"] == "no-store"
    assert len(llm.prompts) == before_calls and len(rows(db, p)) == before_rows


def test_llm_failure_on_refresh_saves_nothing_and_keeps_quota__AC16(client, db, auth, patient):
    p = patient["id"]
    install(client, ScriptedLlm(first_output(), refresh_output(), error_on={2}))
    g1_id = suggest(client, auth, p, p).json()["suggestion_id"]
    r = refresh(client, auth, p, g1_id)
    assert (r.status_code, r.json()) == (502, {"detail": "llm_invalid_output"})
    assert len(rows(db, p)) == 1  # không trả riêng món cũ, không lưu
    ok = refresh(client, auth, p, g1_id)
    assert ok.status_code == 200 and ok.json()["refreshes_remaining"] == 1  # lỗi không trừ lượt


# --- AC27 ---------------------------------------------------------------------------------


def insert_refresh_rows(db, p, previous_id, created_at, n):
    for _ in range(n):
        db.execute(
            text("INSERT INTO meal_suggestions (user_id, suggestion_content, served_from_cache, "
                 "previous_suggestion_id, created_at) "
                 "VALUES (:u, CAST(:c AS jsonb), false, :prev, :t)"),
            {"u": p, "c": '{"meal_type": "trua", "suggestions": []}', "prev": previous_id,
             "t": created_at},
        )


def test_third_refresh_same_day_429__AC27(client, db, auth, patient):
    p = patient["id"]
    llm = install(client, ScriptedLlm(first_output(), refresh_output(), first_output(),
                                      refresh_output()))
    g1 = suggest(client, auth, p, p).json()
    r1 = refresh(client, auth, p, g1["suggestion_id"])
    # Lượt thứ 2 ở bữa khác vẫn tính chung.
    g_toi = suggest(client, auth, p, p, body={**BODY, "meal_type": "toi"}).json()
    assert g_toi["refreshes_remaining"] == 1  # lần gợi ý đầu không bị đếm
    r2 = refresh(client, auth, p, g_toi["suggestion_id"], meal_type="toi")
    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    assert [r1.json()["refreshes_remaining"], r2.json()["refreshes_remaining"]] == [1, 0]
    calls, saved = len(llm.prompts), len(rows(db, p))

    r3 = refresh(client, auth, p, g1["suggestion_id"])
    assert (r3.status_code, r3.json()) == (429, {"detail": "refresh_limit_reached"})
    assert r3.headers["cache-control"] == "no-store"
    assert 1 <= int(r3.headers["retry-after"]) <= 86400
    assert len(llm.prompts) == calls and len(rows(db, p)) == saved

    # Gợi ý đầu (không có previous) vẫn được.
    assert suggest(client, auth, p, p).status_code == 200


def test_refreshes_before_vietnam_midnight_not_counted__AC27(client, db, auth, patient):
    p = patient["id"]
    install(client, ScriptedLlm(first_output(), refresh_output()))
    g1_id = suggest(client, auth, p, p).json()["suggestion_id"]
    today = day_start_vn(datetime.now(UTC))
    insert_refresh_rows(db, p, g1_id, today - timedelta(seconds=1), 2)  # 23:59:59 hôm qua (VN)
    r = refresh(client, auth, p, g1_id)
    assert r.status_code == 200 and r.json()["refreshes_remaining"] == 1

    insert_refresh_rows(db, p, g1_id, today, 1)  # 00:00:00 hôm nay (VN) thì có tính
    r = refresh(client, auth, p, g1_id)
    assert r.status_code == 429


class BlockingLlm:
    """Request đầu tới được LLM sẽ chờ tín hiệu, giữ advisory lock trong lúc chờ."""

    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Event()
        self.calls = 0

    def suggest(self, prompt):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(timeout=30)
        return output(meal("Món đồng thời A"), meal("Món đồng thời B"))


def test_concurrent_refresh_with_one_quota_left_only_one_succeeds__AC27(
    client, db, auth, patient
):
    p = patient["id"]
    install(client, ScriptedLlm(first_output()))
    g1_id = suggest(client, auth, p, p).json()["suggestion_id"]
    insert_refresh_rows(db, p, g1_id, datetime.now(UTC), 1)  # còn đúng 1 lượt

    blocking = BlockingLlm()
    clients = [TestClient(create_app()) for _ in range(2)]
    for c in clients:
        c.app.dependency_overrides[get_meal_suggester] = lambda: blocking

    def call(c):
        return refresh(c, auth, p, g1_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(call, clients[0])
        assert blocking.entered.wait(timeout=30)  # request 1 đang giữ khóa, chờ ở LLM
        second = pool.submit(call, clients[1])
        # Chờ tới khi request 2 thật sự bị chặn ở advisory lock (kiểm pg_locks, không sleep).
        deadline = datetime.now(UTC) + timedelta(seconds=30)
        while datetime.now(UTC) < deadline:
            waiting = db.execute(text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
            )).scalar_one()
            if waiting:
                break
        assert waiting == 1
        blocking.release.set()
        statuses = sorted([first.result().status_code, second.result().status_code])

    assert statuses == [200, 429]
    assert blocking.calls == 1
    refreshed_today = db.execute(
        text("SELECT count(*) FROM meal_suggestions WHERE user_id = :u "
             "AND previous_suggestion_id IS NOT NULL"), {"u": p}).scalar_one()
    assert refreshed_today == 2  # 1 có sẵn + 1 request thắng; không vượt giới hạn 2
