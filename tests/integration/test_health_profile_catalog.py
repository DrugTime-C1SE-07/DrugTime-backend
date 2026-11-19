"""Danh mục hồ sơ sức khỏe nạp từ seed (task adhoc-20261118-health-profile-catalog).

Kỳ vọng đọc từ chính file seed `supabase/seeds/20_health_profile_catalog.sql` (sinh từ workbook
đã được dược sĩ duyệt), để test không gắn cứng số dòng khi danh mục thay đổi. Cần DB vừa
`supabase db reset` (seed đã nạp).
"""

import ast
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

SEED = Path(__file__).resolve().parents[2] / "supabase" / "seeds" / "20_health_profile_catalog.sql"
OLD_IDS = {"penicillin", "aspirin", "cephalosporin", "seafood", "peanuts", "eggs", "milk"}


def _tuples(sql: str, start: str, end: str) -> list[tuple]:
    """VALUES rows of one INSERT block of the generated seed (simple literals only)."""
    block = sql.split(start, 1)[1].split(end, 1)[0]
    rows = []
    for line in block.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("('"):  # data rows start with a quoted value; skip column lists
            continue
        py = re.sub(r"\bNULL\b", "None", line)
        py = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", py))
        rows.append(ast.literal_eval(py.replace("''", "\\'")))
    return rows


@pytest.fixture(scope="module")
def seed():
    sql = SEED.read_text(encoding="utf-8")
    return {
        "sql": sql,
        "conditions": _tuples(sql, "INSERT INTO conditions", ") AS v ("),
        "allergens": _tuples(sql, "INSERT INTO allergens", "ON CONFLICT"),
    }


def test_seed_file_has_reviewed_catalog(seed):
    names = {row[0] for row in seed["conditions"]}
    assert {"Đái tháo đường type 2", "Tăng huyết áp"} <= names
    ids = {row[0] for row in seed["allergens"]}
    assert OLD_IDS <= ids and "sulfa" not in ids and "ace_inhibitor" not in ids
    assert "DELETE" not in seed["sql"].upper() and "TRUNCATE" not in seed["sql"].upper()


def test_seeded_conditions__AC1(client, db, make, auth, seed):
    rows = {
        row.name: (row.medical_nature, row.data_role, row.icd10_code, row.code)
        for row in db.execute(
            text(
                "SELECT c.name, c.medical_nature::text, c.data_role::text, c.icd10_code, g.code "
                "FROM conditions c LEFT JOIN disease_groups g ON g.id = c.disease_group_id"
            )
        )
    }
    for name, nature, role, icd, group in seed["conditions"]:
        assert rows[name] == (nature, role, icd, group), name
    # Physiological states carry no disease group (01 mục 3.1).
    for name, nature, _role, _icd, group in seed["conditions"]:
        if nature == "sinh_ly_binh_thuong":
            assert group is None and rows[name][3] is None

    response = client.get("/conditions?limit=100", headers=auth(make.user(consents=())))
    assert response.status_code == 200
    listed = {row["name"] for row in response.json()["items"]}
    assert {row[0] for row in seed["conditions"]} <= listed


def test_seeded_allergens_endpoint__AC2(client, make, auth, seed):
    headers = auth(make.user(consents=()))
    first = client.get("/allergens", headers=headers)
    second = client.get("/allergens", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()  # stable order between calls
    items = first.json()["items"]
    assert set(items[0]) == {"id", "category", "name"}
    assert all(item["category"] in {"drug", "food"} for item in items)
    categories = [item["category"] for item in items]
    assert categories == sorted(categories, key=lambda c: c != "drug")  # drug before food

    expected = [
        {"id": aid, "category": cat, "name": name}
        for aid, cat, name, _order, active, _source in sorted(
            seed["allergens"], key=lambda r: (r[1] != "drug", r[3], r[0])
        )
        if active
    ]
    seeded_ids = {row["id"] for row in expected}
    assert [item for item in items if item["id"] in seeded_ids] == expected
    assert OLD_IDS <= {item["id"] for item in items}
    assert "sulfa" not in {item["id"] for item in items}


def test_allergens_require_authentication__AC2(client):
    assert client.get("/allergens").status_code == 401


def _counts(db, seed):
    names = [row[0] for row in seed["conditions"]]
    ids = [row[0] for row in seed["allergens"]]
    return (
        db.execute(
            text("SELECT count(*) FROM conditions WHERE name = ANY(:n)"), {"n": names}
        ).scalar(),
        db.execute(text("SELECT count(*) FROM allergens WHERE id = ANY(:i)"), {"i": ids}).scalar(),
        db.execute(text("SELECT count(*) FROM conditions")).scalar(),
        db.execute(text("SELECT count(*) FROM allergens")).scalar(),
    )


def test_catalog_seed_rerun_is_idempotent__AC6(db, seed):
    before = _counts(db, seed)
    assert before[:2] == (len(seed["conditions"]), len(seed["allergens"]))
    db.exec_driver_sql(seed["sql"])
    db.exec_driver_sql(seed["sql"])
    assert _counts(db, seed) == before


def test_catalog_seed_can_swap_display_order__AC6(db, seed):
    drugs = sorted((r for r in seed["allergens"] if r[1] == "drug"), key=lambda r: r[3])
    a, b = drugs[0], drugs[1]
    swapped = seed["sql"]
    for row, new_order in ((a, b[3]), (b, a[3])):
        old = f"('{row[0]}', 'drug', "
        line = next(ln for ln in swapped.splitlines() if ln.strip().startswith(old))
        swapped = swapped.replace(line, line.replace(f", {row[3]}, ", f", {new_order}, ", 1), 1)
    try:
        db.exec_driver_sql(swapped)
        orders = dict(
            db.execute(
                text("SELECT id, display_order FROM allergens WHERE id IN (:a, :b)"),
                {"a": a[0], "b": b[0]},
            ).all()
        )
        assert orders == {a[0]: b[3], b[0]: a[3]}
    finally:
        db.exec_driver_sql(seed["sql"])  # restore the reviewed order
    restored = dict(
        db.execute(
            text("SELECT id, display_order FROM allergens WHERE id IN (:a, :b)"),
            {"a": a[0], "b": b[0]},
        ).all()
    )
    assert restored == {a[0]: a[3], b[0]: b[3]}


def test_catalog_seed_does_not_touch_patient_data__AC6(db, make, seed):
    user = make.user()
    db.execute(
        text(
            "INSERT INTO health_profile_setup (user_id, revision, allergen_ids) "
            "VALUES (:u, 1, ARRAY['penicillin'])"
        ),
        {"u": user},
    )
    before = db.execute(text("SELECT count(*) FROM user_conditions")).scalar()
    db.exec_driver_sql(seed["sql"])
    assert db.execute(text("SELECT count(*) FROM user_conditions")).scalar() == before
    row = db.execute(
        text("SELECT revision, allergen_ids FROM health_profile_setup WHERE user_id = :u"),
        {"u": user},
    ).one()
    assert (row.revision, row.allergen_ids) == (1, ["penicillin"])


def test_allergens_privileges_and_constraints(db, role_engines):
    for role in ("anon", "authenticated", "service_role", "worker_role", "api_role"):
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            has = db.execute(
                text("SELECT has_table_privilege(:r, 'public.allergens', :p)"),
                {"r": role, "p": priv},
            ).scalar()
            assert has == (role == "api_role" and priv == "SELECT"), (role, priv)

    with role_engines["api_role"].connect() as api:
        assert api.execute(text("SELECT count(*) FROM allergens")).scalar() > 0
        for sql in (
            "INSERT INTO allergens (id, category, name, display_order, source) "
            "VALUES ('t_api', 'food', 'x', 999, 'x')",
            "UPDATE allergens SET is_active = false",
            "DELETE FROM allergens",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                api.execute(text(sql))
            api.rollback()

    for sql in ("DELETE FROM allergens WHERE id = 'penicillin'", "TRUNCATE allergens"):
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            db.execute(text(sql))
    assert db.execute(text("SELECT count(*) FROM allergens WHERE id = 'penicillin'")).scalar() == 1

    insert = (
        "INSERT INTO allergens (id, category, name, display_order, source) "
        "VALUES (:id, :category, :name, :order, :source)"
    )
    good = {"id": "t_check", "category": "food", "name": "x", "order": 9999, "source": "s"}
    for field, value in (
        ("id", "Bad-ID"),
        ("category", "pollen"),
        ("name", "  "),
        ("order", 0),
        ("source", " "),
    ):
        with pytest.raises(DBAPIError, match="check constraint"):
            db.execute(text(insert), {**good, field: value})
