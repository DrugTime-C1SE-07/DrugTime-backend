"""Seed kho tri thức dược thật (task 4.04: AC2, AC5–AC9, AC17).

Chạy trên DB vừa `supabase db reset` với supabase/seeds/10_knowledge_base.sql. Bộ test tích hợp
không dọn dữ liệu, nên test nhận diện dữ liệu seed qua tên hoạt chất và tên thuốc lấy từ file seed,
không đếm toàn bảng. Test chọn thuốc mẫu theo tiêu chí truy vấn (không cứng tên) để workbook đổi vẫn
chạy được. DB chưa nạp seed thì skip, có ghi lý do.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "supabase" / "seeds" / "10_knowledge_base.sql"
MOCK_SEED = ROOT / "supabase" / "seeds" / "90_mock_drug_food.sql"
PAGE = re.compile(r"\btr\.\s*\d+", re.IGNORECASE)


def _block_first_strings(sql: str, title: str) -> list[str]:
    """Chuỗi đầu tiên của mỗi bộ giá trị trong khối `-- <title>` của file seed."""
    start = sql.index(f"\n-- {title}")
    end = sql.find("\n-- ", start + 4)
    block = sql[start : end if end != -1 else len(sql)]
    return re.findall(r"^\s+\('((?:[^']|'')*)'", block, re.M)


@pytest.fixture(scope="module")
def seed():
    if not SEED.exists():
        pytest.skip("Chưa có supabase/seeds/10_knowledge_base.sql")
    sql = SEED.read_text(encoding="utf-8")
    counts = {t: int(n) for t, n in re.findall(r"^-- count (\w+)=(\d+)$", sql, re.M)}
    ingredients = [s.replace("''", "'") for s in _block_first_strings(sql, "active_ingredients")]
    medications = [s.replace("''", "'") for s in _block_first_strings(sql, "medications")]
    return {"sql": sql, "counts": counts, "ingredients": ingredients, "medications": medications}


@pytest.fixture
def seeded(db, seed):
    loaded = db.execute(
        text("SELECT count(*) FROM active_ingredients WHERE standard_name = ANY(:n)"),
        {"n": seed["ingredients"]},
    ).scalar_one()
    if loaded == 0:
        pytest.skip("DB chưa nạp seed thật (cần `supabase db reset`)")
    return seed


def _ids(db, names):
    rows = db.execute(
        text("SELECT standard_name, id FROM active_ingredients WHERE standard_name = ANY(:n)"),
        {"n": list(names)},
    )
    return {r.standard_name: r.id for r in rows}


def _seed_med(db, seed, where: str, params: dict | None = None) -> dict:
    """Thuốc mẫu của seed (một hoạt chất) thỏa điều kiện SQL trên hoạt chất `a`."""
    row = db.execute(
        text(
            "SELECT m.id, m.name, a.id AS ingredient_id, a.standard_name FROM medications m "
            "JOIN medication_active_ingredients mai ON mai.medication_id = m.id "
            "JOIN active_ingredients a ON a.id = mai.active_ingredient_id "
            "WHERE m.name = ANY(:meds) AND m.source IS NULL AND m.deleted_at IS NULL "
            "AND (SELECT count(*) FROM medication_active_ingredients x "
            "     WHERE x.medication_id = m.id) = 1 "
            f"AND {where} ORDER BY m.name LIMIT 1"
        ),
        {"meds": seed["medications"], **(params or {})},
    ).first()
    if row is None:
        pytest.skip(f"Seed không có thuốc mẫu thỏa điều kiện: {where}")
    return dict(row._mapping)


def _add(client, auth, patient, scheduled_body, medication_id):
    r = client.post("/medications", json=scheduled_body(medication_id), headers=auth(patient))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _food(client, auth, patient):
    r = client.get(f"/patients/{patient}/food-interactions", headers=auth(patient))
    assert r.status_code == 200, r.text
    return r.json()


def _check(client, auth, patient, **body):
    r = client.post(f"/patients/{patient}/interaction-checks", json=body, headers=auth(patient))
    assert r.status_code == 200, r.text
    return r.json()


CURRENT = "superseded_at IS NULL AND deleted_at IS NULL"


# ---------------------------------------------------------------- AC9, AC2


def test_seed_reset_counts_and_no_mock__AC9(db, seeded):
    seed = seeded
    assert not MOCK_SEED.exists(), "seed mock phải bị xóa (G13)"
    assert seed["sql"].count("BEGIN;") == 1 and seed["sql"].rstrip().endswith("COMMIT;")
    ids = list(_ids(db, seed["ingredients"]).values())
    assert len(ids) == seed["counts"]["active_ingredients"] == len(seed["ingredients"])

    def one(q, **p):
        return db.execute(text(q), {"ids": ids, "meds": seed["medications"], **p}).scalar_one()

    expected = {
        "ingredient_aliases": one(
            "SELECT count(*) FROM ingredient_aliases WHERE active_ingredient_id = ANY(:ids)"
        ),
        "medications": one(
            "SELECT count(*) FROM medications WHERE name = ANY(:meds) AND source IS NULL"
        ),
        "medication_active_ingredients": one(
            "SELECT count(*) FROM medication_active_ingredients x JOIN medications m "
            "ON m.id = x.medication_id WHERE m.name = ANY(:meds) AND m.source IS NULL"
        ),
        "active_ingredient_interactions": one(
            "SELECT count(*) FROM active_ingredient_interactions WHERE ingredient_a_id = ANY(:ids) "
            f"AND ingredient_b_id = ANY(:ids) AND {CURRENT}"
        ),
        "active_ingredient_interaction_dose_thresholds": one(
            "SELECT count(*) FROM active_ingredient_interaction_dose_thresholds t "
            "JOIN active_ingredient_interactions i ON i.id = t.interaction_id "
            "WHERE i.ingredient_a_id = ANY(:ids) AND i.ingredient_b_id = ANY(:ids) "
            "AND i.superseded_at IS NULL AND i.deleted_at IS NULL"
        ),
        "drug_food_interactions": one(
            f"SELECT count(*) FROM drug_food_interactions WHERE active_ingredient_id = ANY(:ids) "
            f"AND {CURRENT}"
        ),
    }
    for table, n in expected.items():
        assert n == seed["counts"][table], table
    mock = one(
        "SELECT (SELECT count(*) FROM medications WHERE name LIKE '[MOCK]%') "
        "+ (SELECT count(*) FROM active_ingredients WHERE standard_name LIKE 'MOCK %') "
        "+ (SELECT count(*) FROM drug_food_interactions WHERE source LIKE 'MOCK%')"
    )
    assert mock == 0


def test_seeded_rules_all_verified_and_cited__AC2(db, seeded):
    ids = list(_ids(db, seeded["ingredients"]).values())
    drug = db.execute(
        text(
            "SELECT verification_status, source FROM active_ingredient_interactions "
            f"WHERE ingredient_a_id = ANY(:ids) AND {CURRENT}"
        ),
        {"ids": ids},
    ).all()
    food = db.execute(
        text(
            "SELECT verification_status, source FROM drug_food_interactions "
            f"WHERE active_ingredient_id = ANY(:ids) AND {CURRENT}"
        ),
        {"ids": ids},
    ).all()
    assert drug and food
    for r in [*drug, *food]:
        assert r.verification_status == "da_xac_minh"
        assert PAGE.search(r.source), r.source


# ---------------------------------------------------------------- thuốc–thức ăn


def test_seed_food_lists_all_rules__AC5(client, make, auth, scheduled_body, db, seeded):
    med = _seed_med(
        db,
        seeded,
        f"(SELECT count(*) FROM drug_food_interactions d WHERE d.active_ingredient_id = a.id "
        f"AND d.{CURRENT}) >= 2",
    )
    rules = db.execute(
        text(
            "SELECT food_to_avoid, severity_level, source FROM drug_food_interactions "
            f"WHERE active_ingredient_id = :a AND {CURRENT}"
        ),
        {"a": med["ingredient_id"]},
    ).all()
    patient = make.user()
    _add(client, auth, patient, scheduled_body, med["id"])

    body = _food(client, auth, patient)
    assert body["status"] == "co_tuong_tac"
    [m] = body["medications"]
    assert m["status"] == "co_tuong_tac"
    got = {(w["food_to_avoid"], w["severity_level"], w["source"]) for w in m["warnings"]}
    assert got == {(r.food_to_avoid, r.severity_level, r.source) for r in rules}
    assert len(m["warnings"]) == len(rules) >= 2
    assert all(PAGE.search(w["source"]) for w in m["warnings"])


def test_seed_food_none_found__AC6(client, make, auth, scheduled_body, db, seeded):
    med = _seed_med(
        db,
        seeded,
        f"NOT EXISTS (SELECT 1 FROM drug_food_interactions d WHERE d.active_ingredient_id = a.id "
        f"AND d.{CURRENT})",
    )
    patient = make.user()
    _add(client, auth, patient, scheduled_body, med["id"])

    body = _food(client, auth, patient)
    assert body["status"] == "da_kiem_tra_khong_thay"
    assert body["medications"][0]["warnings"] == []


def test_seed_insufficient_without_ingredients__AC7(client, make, auth, scheduled_body, db, seeded):
    seeded_med = _seed_med(db, seeded, "TRUE")
    bare = make.catalog_medication(with_ingredient=False)
    patient = make.user()
    _add(client, auth, patient, scheduled_body, bare)

    assert _food(client, auth, patient)["status"] == "khong_du_du_lieu"
    check = _check(client, auth, patient)
    assert check["status"] == "khong_du_du_lieu"
    assert [m["medication_id"] for m in check["insufficient_data_medications"]] == [bare]

    # Cùng người bệnh thêm thuốc seed có hoạt chất: thuốc thiếu dữ liệu vẫn được liệt kê riêng.
    _add(client, auth, patient, scheduled_body, seeded_med["id"])
    check = _check(client, auth, patient)
    assert bare in [m["medication_id"] for m in check["insufficient_data_medications"]]


# ---------------------------------------------------------------- thuốc–thuốc


def _rule(db, a_id, b_id):
    return (
        db.execute(
            text(
                "SELECT * FROM active_ingredient_interactions WHERE "
                "((ingredient_a_id = :a AND ingredient_b_id = :b) OR "
                f"(ingredient_a_id = :b AND ingredient_b_id = :a)) AND {CURRENT}"
            ),
            {"a": a_id, "b": b_id},
        )
        .mappings()
        .first()
    )


def test_seed_drug_gliclazid_miconazol__AC8(client, make, auth, scheduled_body, db, seeded):
    ids = _ids(db, ["Gliclazid", "Miconazol"])
    if len(ids) < 2 or _rule(db, ids["Gliclazid"], ids["Miconazol"]) is None:
        pytest.skip("Seed không có quy tắc Gliclazid–Miconazol đã duyệt")
    rule = _rule(db, ids["Gliclazid"], ids["Miconazol"])
    gli = _seed_med(db, seeded, "a.standard_name = 'Gliclazid'")
    mic = _seed_med(db, seeded, "a.standard_name = 'Miconazol'")
    patient = make.user()
    _add(client, auth, patient, scheduled_body, gli["id"])
    _add(client, auth, patient, scheduled_body, mic["id"])

    body = _check(client, auth, patient)
    assert body["status"] == "co_tuong_tac"
    [f] = body["interactions"]
    assert {f["ingredient_a_name"], f["ingredient_b_name"]} == {"Gliclazid", "Miconazol"}
    assert f["severity_level"] == rule["severity_level"] == 4
    assert f["description"] == rule["description"]
    assert f["source"] == rule["source"] and PAGE.search(f["source"])
    assert body["insufficient_data_medications"] == []


def test_seed_drug_combo_lists_all_pairs__AC8(client, make, auth, scheduled_body, db, seeded):
    """Thuốc phối hợp + một thuốc khác: mọi cặp có quy tắc giữa hai thuốc đều được liệt kê."""
    combo = db.execute(
        text(
            "SELECT m.id, array_agg(x.active_ingredient_id) AS ings FROM medications m "
            "JOIN medication_active_ingredients x ON x.medication_id = m.id "
            "WHERE m.name = ANY(:meds) AND m.source IS NULL GROUP BY m.id "
            "HAVING count(*) >= 2 ORDER BY m.id"
        ),
        {"meds": seeded["medications"]},
    ).all()
    for c in combo:
        other = db.execute(
            text(
                "SELECT m.id, x.active_ingredient_id AS ing, "
                "       count(DISTINCT i.id) AS n FROM medications m "
                "JOIN medication_active_ingredients x ON x.medication_id = m.id "
                "JOIN active_ingredient_interactions i ON i.superseded_at IS NULL "
                "  AND i.deleted_at IS NULL AND ("
                "  (i.ingredient_a_id = x.active_ingredient_id AND i.ingredient_b_id = ANY(:c)) OR "
                "  (i.ingredient_b_id = x.active_ingredient_id AND i.ingredient_a_id = ANY(:c))) "
                "WHERE m.name = ANY(:meds) AND m.source IS NULL AND m.id <> :cid "
                "AND (SELECT count(*) FROM medication_active_ingredients y "
                "     WHERE y.medication_id = m.id) = 1 "
                "GROUP BY m.id, x.active_ingredient_id HAVING count(DISTINCT i.id) >= 2 "
                "ORDER BY m.id LIMIT 1"
            ),
            {"c": list(c.ings), "cid": c.id, "meds": seeded["medications"]},
        ).first()
        if other:
            break
    else:
        pytest.skip("Seed không có thuốc phối hợp tương tác với ≥ 2 hoạt chất của một thuốc khác")
    expected = {
        frozenset((r.ingredient_a_id, r.ingredient_b_id))
        for r in db.execute(
            text(
                "SELECT ingredient_a_id, ingredient_b_id FROM active_ingredient_interactions "
                f"WHERE {CURRENT} AND ((ingredient_a_id = :o AND ingredient_b_id = ANY(:c)) OR "
                "(ingredient_b_id = :o AND ingredient_a_id = ANY(:c)))"
            ),
            {"o": other.ing, "c": list(c.ings)},
        )
    }
    patient = make.user()
    _add(client, auth, patient, scheduled_body, c.id)
    _add(client, auth, patient, scheduled_body, other.id)

    body = _check(client, auth, patient)
    assert body["status"] == "co_tuong_tac"
    got = {frozenset((f["ingredient_a_id"], f["ingredient_b_id"])) for f in body["interactions"]}
    assert got == expected and len(got) >= 2


# ---------------------------------------------------------------- ngưỡng liều (AC17)


def _threshold_case(db):
    """Quy tắc có ngưỡng: (quy tắc, hoạt chất ở phía ngưỡng, hoạt chất kia, ngưỡng theo min)."""
    rows = (
        db.execute(
            text(
                "SELECT i.id AS rule_version, i.severity_level AS base, i.ingredient_a_id AS a, "
                "i.ingredient_b_id AS b, t.ingredient_ref, t.min_dose, t.max_dose, t.dose_unit, "
                "t.severity_level, t.warning_text "
                "FROM active_ingredient_interaction_dose_thresholds t "
                "JOIN active_ingredient_interactions i ON i.id = t.interaction_id "
                "WHERE i.superseded_at IS NULL AND i.deleted_at IS NULL "
                "ORDER BY (i.severity_level = 4) DESC, i.id, t.min_dose NULLS FIRST"
            )
        )
        .mappings()
        .all()
    )
    by_rule: dict[int, list] = {}
    for r in rows:
        by_rule.setdefault(r["rule_version"], []).append(r)
    for items in by_rule.values():
        if (
            len(items) >= 2
            and items[0]["max_dose"] is not None
            and items[-1]["min_dose"] is not None
        ):
            return items
    return None


def test_seed_dose_threshold_applies_to_candidate__AC17(
    client, make, auth, scheduled_body, db, seeded
):
    items = _threshold_case(db)
    if items is None:
        pytest.skip("Chưa có quy tắc nào có ngưỡng thấp và ngưỡng cao được duyệt")
    low, high = items[0], items[-1]
    ref_ing = low["a"] if low["ingredient_ref"] == "A" else low["b"]
    other_ing = low["b"] if low["ingredient_ref"] == "A" else low["a"]
    ref_med = _seed_med(db, seeded, "a.id = :i", {"i": ref_ing})
    other_med = _seed_med(db, seeded, "a.id = :i", {"i": other_ing})
    patient = make.user()
    _add(client, auth, patient, scheduled_body, other_med["id"])

    def finding(**dose):
        body = _check(client, auth, patient, candidate_medication_id=ref_med["id"], **dose)
        assert body["status"] == "co_tuong_tac"
        [f] = [
            f
            for f in body["interactions"]
            if {f["ingredient_a_id"], f["ingredient_b_id"]} == {ref_ing, other_ing}
        ]
        return f

    low_dose = float(low["max_dose"])
    high_dose = float(high["min_dose"])
    f = finding(candidate_dose_amount=low_dose, candidate_dose_unit=low["dose_unit"])
    assert (f["severity_level"], f["warning_message"]) == (
        low["severity_level"],
        low["warning_text"],
    )
    f = finding(candidate_dose_amount=high_dose, candidate_dose_unit=high["dose_unit"])
    assert (f["severity_level"], f["warning_message"]) == (
        high["severity_level"],
        high["warning_text"],
    )
    # Không gửi liều (như thuốc đang dùng hiện nay): mức gốc của quy tắc (R8).
    f = finding()
    assert f["severity_level"] == low["base"]
    # Liều đúng nhưng khác đơn vị: không áp ngưỡng (không tự quy đổi, QD-38).
    f = finding(candidate_dose_amount=low_dose / 1000, candidate_dose_unit="g")
    assert f["severity_level"] == low["base"]
