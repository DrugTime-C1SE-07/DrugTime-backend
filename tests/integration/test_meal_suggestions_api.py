"""POST /patients/{patient_id}/meal-suggestions với Postgres thật (task 4.26).

AC2, AC6d, AC10, AC11, AC12, AC12b, AC13. LLM giả qua dependency override; không gọi Claude.

Không phụ thuộc `backend/.env` của máy dev: fixture autouse ép tắt LLM thật cho mọi test, nên
request không bao giờ ra tới Anthropic kể cả khi `.env` có key và bật cờ.
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from drugtime.modules.ai_meal.adapters.inbound.http import get_meal_suggester
from drugtime.modules.ai_meal.domain.errors import LlmInvalidOutput, LlmUnavailable
from drugtime.shared.config import get_settings


def disable_real_llm(monkeypatch):
    """Biến môi trường thắng giá trị trong .env (pydantic-settings)."""
    monkeypatch.setenv("AI_MEAL_LLM_ENABLED", "false")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    disable_real_llm(monkeypatch)
    yield
    get_settings.cache_clear()  # monkeypatch khôi phục env sau fixture; settings đọc lại lần sau

RULES = "/admin/drug-food-interactions"
SCOPE = "goi_y_bua_an"
AVOID = "Thực phẩm giàu kali (chuối, cam)"
DISCLAIMER = (
    "Gợi ý do AI tạo, chỉ mang tính tham khảo, không thay thế tư vấn của bác sĩ hay "
    "chuyên gia dinh dưỡng. Hãy hỏi bác sĩ hoặc dược sĩ trước khi thay đổi chế độ ăn."
)
RESPONSE_KEYS = {"suggestion_id", "meal_type", "suggestions", "food_check", "disclaimer",
                 "created_at"}
BODY = {
    "meal_type": "trua",
    "allergies": {"none": False, "items": ["Tôm"]},
    "dietary_restrictions": {"none": True, "items": []},
    "preferences": ["Ít cay"],
}


def meal(name, *, benefits=None, ingredients=("Gà",)):
    return {
        "name": name,
        "tags": ["Ít muối"],
        "kcal_estimate": 480,
        "cook_minutes": 25,
        "benefits": benefits or [
            {"text": "Ít muối, tốt cho huyết áp", "related_to": "condition:1"},
            {"text": "Nhiều chất xơ", "related_to": "general"},
        ],
        "ingredients": [
            {"name": i, "amount": "100 g", "group": "chinh", "use_sparingly": False}
            for i in ingredients
        ],
    }


def output(*meals, meal_type="trua"):
    return json.dumps({"meal_type": meal_type, "suggestions": list(meals)}, ensure_ascii=False)


class FakeLlm:
    def __init__(self, raw=None, error=None):
        self.raw = raw or output(meal("Cơm gà luộc"), meal("Bún cá rô", ingredients=("Cá rô",)))
        self.error = error
        self.prompts = []

    def suggest(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.raw


def install_fake_llm(client) -> FakeLlm:
    fake = FakeLlm()
    client.app.dependency_overrides[get_meal_suggester] = lambda: fake
    return fake


@pytest.fixture
def llm(client):
    return install_fake_llm(client)


def log(actor, role, result, reason=None):
    return {"actor_user_id": actor, "actor_role": role, "data_scope": SCOPE, "result": result,
            "rejection_reason": reason}


def meal_rows(db, patient):
    rows = db.execute(
        text("SELECT suggestion_content, served_from_cache FROM meal_suggestions "
             "WHERE user_id = :u ORDER BY id"),
        {"u": patient},
    )
    return [dict(r._mapping) for r in rows]


def add_condition(db, patient, name):
    cid = db.execute(
        text("INSERT INTO conditions (name, medical_nature, data_role) "
             "VALUES (:n, 'benh_ly', 'dieu_chinh_thuoc_khac') RETURNING id"),
        {"n": name},
    ).scalar_one()
    db.execute(
        text("INSERT INTO user_conditions (user_id, condition_id) VALUES (:u, :c)"),
        {"u": patient, "c": cid},
    )


def add_rule(client, admin_h, ingredient_id, food=AVOID, severity=2):
    r = client.post(
        RULES,
        json={"ingredient_id": ingredient_id, "food_to_avoid": food, "severity_level": severity,
              "reason": "Tăng kali máu", "source": "Dược thư"},
        headers=admin_h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def add_med(client, auth, patient, scheduled_body, medication_id):
    r = client.post("/medications", json=scheduled_body(medication_id), headers=auth(patient))
    assert r.status_code == 201, r.text


def create_patient(client, db, make, auth, admin_auth, scheduled_body) -> dict:
    """Người bệnh có consent ai_meal, một thuốc có quy tắc thực phẩm và một bệnh nền.

    Trả dict: id, ingredient (tên hoạt chất), condition (tên bệnh), rule (quy tắc).
    """
    p = make.user(consents=("health_data", "ai_meal"))
    ingredient = f"Losartan {uuid4().hex[:6]}"
    iid = make.ingredient(name=ingredient)
    rule = add_rule(client, admin_auth[1], iid)
    add_med(client, auth, p, scheduled_body, make.medication_with([iid]))
    condition = f"Tăng huyết áp {uuid4().hex[:6]}"
    add_condition(db, p, condition)
    return {"id": p, "ingredient": ingredient, "condition": condition, "rule": rule}


@pytest.fixture
def patient(client, db, make, auth, admin_auth, scheduled_body):
    return create_patient(client, db, make, auth, admin_auth, scheduled_body)


def suggest(client, auth, caller, patient_id, body=BODY):
    return client.post(f"/patients/{patient_id}/meal-suggestions", json=body,
                       headers=auth(caller))


def test_self_success__AC11(client, db, make, auth, llm, patient):
    p = patient["id"]
    r = suggest(client, auth, p, p)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert set(data) == RESPONSE_KEYS
    assert data["meal_type"] == "trua" and data["disclaimer"] == DISCLAIMER
    assert data["created_at"].endswith("+07:00")
    assert [m["name"] for m in data["suggestions"]] == ["Cơm gà luộc", "Bún cá rô"]
    assert data["suggestions"][0]["benefits"][0]["related_to"] == {
        "type": "condition", "label": patient["condition"]}
    assert data["food_check"]["status"] == "co_tuong_tac"
    [w] = data["food_check"]["warnings"]
    assert (w["rule_id"], w["food_to_avoid"], w["ingredient"]["standard_name"]) == (
        patient["rule"]["id"], AVOID, patient["ingredient"])

    assert make.access_logs(p) == [log(p, "patient", "allowed")]
    [row] = meal_rows(db, p)
    assert row["served_from_cache"] is False
    content = row["suggestion_content"]
    assert content["prompt_version"] == "meal-v1" and content["meal_type"] == "trua"
    assert data["suggestion_id"] == db.execute(
        text("SELECT id FROM meal_suggestions WHERE user_id = :u"), {"u": p}).scalar_one()
    assert "Tôm" not in json.dumps(content, ensure_ascii=False)  # không lưu dị ứng thô
    assert len(llm.prompts) == 1


def test_llm_payload_minimal__AC2(client, db, auth, llm, patient):
    p = patient["id"]
    assert suggest(client, auth, p, p).status_code == 200
    prompt = llm.prompts[0]
    payload = prompt.system + prompt.user
    for expected in (patient["ingredient"], patient["condition"], AVOID, "Tôm", "Ít cay"):
        assert expected in payload
    email, name = db.execute(
        text("SELECT email, full_name FROM users WHERE id = :u"), {"u": p}).one()
    for leaked in (str(p), email, name):
        assert leaked not in payload


@pytest.mark.parametrize(
    "fake,status,detail",
    [
        (FakeLlm(error=LlmUnavailable("timeout")), 503, "llm_unavailable"),
        (FakeLlm(error=LlmUnavailable("rate_limited")), 503, "llm_unavailable"),
        (FakeLlm(error=LlmInvalidOutput("refusal")), 502, "llm_invalid_output"),
        (FakeLlm(raw="Xin lỗi, tôi không thể"), 502, "llm_invalid_output"),
        (FakeLlm(raw=output(meal("Cơm"), meal_type="toi")), 502, "llm_invalid_output"),
    ],
    ids=["timeout", "rate_limited", "refusal", "not_json", "wrong_meal_type"],
)
def test_llm_invalid_or_unavailable__AC12(client, db, make, auth, patient, fake, status, detail):
    client.app.dependency_overrides[get_meal_suggester] = lambda: fake
    p = patient["id"]
    r = suggest(client, auth, p, p)
    assert (r.status_code, r.json()) == (status, {"detail": detail})
    assert r.headers["cache-control"] == "no-store"
    assert "Cơm" not in r.text
    assert meal_rows(db, p) == []
    # Dữ liệu sức khỏe đã được đọc: dòng allowed vẫn được giữ.
    assert make.access_logs(p) == [log(p, "patient", "allowed")]


def test_llm_disabled_503__AC10(client, db, make, auth, patient):
    # Không override: dùng dependency thật với AI_MEAL_LLM_ENABLED=false, LLM_API_KEY rỗng
    # (ép bởi fixture `_no_real_llm`, bất kể .env).
    settings = get_settings()
    assert not settings.ai_meal_llm_enabled and not settings.llm_api_key.get_secret_value()
    p = patient["id"]
    r = suggest(client, auth, p, p)
    assert (r.status_code, r.json()) == (503, {"detail": "llm_disabled"})
    assert r.headers["cache-control"] == "no-store"
    assert meal_rows(db, p) == []


INVALID = {
    "missing_allergies": {k: v for k, v in BODY.items() if k != "allergies"},
    "none_false_empty": {**BODY, "allergies": {"none": False, "items": []}},
    "none_true_items": {**BODY, "dietary_restrictions": {"none": True, "items": ["Chay"]}},
    "meal_type_khuya": {**BODY, "meal_type": "khuya"},
}


@pytest.mark.parametrize("body", INVALID.values(), ids=INVALID.keys())
def test_invalid_body_422_no_llm__AC12b(client, db, make, auth, llm, patient, body):
    p = patient["id"]
    r = suggest(client, auth, p, p, body)
    assert r.status_code == 422
    assert llm.prompts == [] and meal_rows(db, p) == []
    assert make.access_logs(p) == []  # body bị từ chối trước khi chạm dữ liệu sức khỏe


@pytest.mark.parametrize("case", ["no_medication", "no_ingredient", "no_rule"])
def test_food_check_status_states__AC13(client, make, auth, llm, scheduled_body, case):
    p = make.user(consents=("health_data", "ai_meal"))
    if case == "no_ingredient":
        add_med(client, auth, p, scheduled_body, make.catalog_medication(with_ingredient=False))
    elif case == "no_rule":
        add_med(client, auth, p, scheduled_body, make.medication_with([make.ingredient()]))
    llm.raw = output(meal("Cơm gà", benefits=[{"text": "Đủ đạm", "related_to": "general"}]))
    r = suggest(client, auth, p, p)
    assert r.status_code == 200, r.text
    expected = "da_kiem_tra_khong_thay" if case == "no_rule" else "khong_du_du_lieu"
    assert r.json()["food_check"] == {"status": expected, "warnings": []}


def test_food_check_recomputed_each_request__AC13(client, auth, admin_auth, llm, patient):
    p, rule = patient["id"], patient["rule"]
    assert suggest(client, auth, p, p).json()["food_check"]["status"] == "co_tuong_tac"
    r = client.delete(f"{RULES}/{rule['id']}", params={"expected_version": 1},
                      headers=admin_auth[1])
    assert r.status_code == 204, r.text
    check = suggest(client, auth, p, p).json()["food_check"]
    assert check == {"status": "da_kiem_tra_khong_thay", "warnings": []}
    # Quy tắc đã xóa không còn trong prompt lần sau.
    assert AVOID in llm.prompts[0].user and AVOID not in llm.prompts[1].user


def test_meal_with_avoid_food_filtered_end_to_end__AC6d(client, db, auth, llm, patient):
    p = patient["id"]
    llm.raw = output(
        meal("Sinh tố chuối", ingredients=("Chuối tiêu", "Sữa chua")),
        meal("Canh tôm chua"),
        meal("Cơm gà luộc"),
    )
    r = suggest(client, auth, p, p)
    assert r.status_code == 200, r.text
    assert [m["name"] for m in r.json()["suggestions"]] == ["Cơm gà luộc"]

    llm.raw = output(meal("Sinh tố chuối", ingredients=("Chuối",)), meal("Tôm rang"))
    r = suggest(client, auth, p, p)
    assert (r.status_code, r.json()) == (502, {"detail": "llm_invalid_output"})
    assert len(meal_rows(db, p)) == 1  # chỉ lần thành công được lưu


def test_commit_failure_503_no_data_nothing_saved__AC17_M2(db, make, auth, patient):
    """Lỗi CSDL khi commit (access_logs + meal_suggestions) → 503 service_unavailable (contract)."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from sqlalchemy.engine.base import RootTransaction
    from sqlalchemy.exc import OperationalError

    from drugtime.main import create_app

    p = patient["id"]
    client = TestClient(create_app(), raise_server_exceptions=False)
    fake = install_fake_llm(client)

    def failing_commit(self):
        raise OperationalError("COMMIT", {}, Exception("simulated commit failure"))

    with patch.object(RootTransaction, "commit", failing_commit):
        r = suggest(client, auth, p, p)
    assert (r.status_code, r.json()) == (503, {"detail": "service_unavailable"})
    assert r.headers["cache-control"] == "no-store"
    assert "Cơm" not in r.text and patient["condition"] not in r.text
    assert len(fake.prompts) == 1  # lỗi xảy ra lúc commit, sau khi đã gọi LLM
    assert make.access_logs(p) == [] and meal_rows(db, p) == []
