"""POST /catalog/medications/match on local PostgreSQL as api_role (task 4.13).

Catalog rows are synthetic and carry a random letters-only tag, so tests never depend on
each other or on catalog data left by other tests (the catalog table is shared).
"""

from uuid import uuid4

import pytest
from sqlalchemy import event, text

PATH = "/catalog/medications/match"
CONTRACT_ITEM_KEYS = {
    "id", "name", "active_ingredient", "strength_text", "dosage_form",
    "has_active_ingredients", "score",
}


@pytest.fixture
def tag():
    """Letters only: survives 4.12 name keys and gives trigram room around the misread.

    Ends with "x": 4.12 reads a word ending in "g" right after an amount ("500mg …g") as a
    strength unit, which would make the synthetic strength unparsed at random.
    """
    return "zq" + "".join(chr(ord("a") + int(c, 16) % 26) for c in uuid4().hex[:8]) + "x"


def add_med(db, make, name, strength, *, ingredient=None, form="Viên nén", deleted=False):
    mid = make.catalog_medication(
        name=name, active_ingredient=ingredient, dosage_form=form, deleted=deleted
    )
    db.execute(
        text("UPDATE medications SET strength_text = :s WHERE id = :i"), {"s": strength, "i": mid}
    )
    return mid


def match(client, headers, body):
    return client.post(PATH, json=body, headers=headers)


def ok(response):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def item_ids(body):
    return [item["id"] for item in body["items"]]


def test_blister_text_matched_end_to_end__AC1_AC12(client, make, auth, db, tag):
    mid = add_med(
        db, make, f"Panadol Extra {tag}", "500 mg + 65 mg",
        ingredient=f"Paracetamol{tag}, Caffeine{tag}",
    )
    aid = make.ingredient(aliases=(f"Paracetamol{tag}",))
    db.execute(
        text(
            "INSERT INTO medication_active_ingredients (medication_id, active_ingredient_id, "
            "strength_value, strength_unit, dosing_unit) VALUES (:m, :a, 500, 'mg', 'vien')"
        ),
        {"m": mid, "a": aid},
    )
    text_ocr = (
        f"PANAD0L EXTRA {tag.upper()}\r\n"
        f"Paracetamol{tag} 500mg Caffeine{tag} 65mg\n"
        f"Panadol Extra {tag}\nHSD 12/2027 Lô 123"
    )
    body = ok(match(client, auth(make.user()), {"text": text_ocr}))
    assert body["status"] == "matched"
    assert body["preselected_id"] == mid == body["items"][0]["id"]
    assert body["suggested_query"] is None
    item = body["items"][0]
    assert set(item) == CONTRACT_ITEM_KEYS
    assert item["name"] == f"Panadol Extra {tag}"
    assert item["active_ingredient"] == f"Paracetamol{tag}, Caffeine{tag}"
    assert item["strength_text"] == "500 mg + 65 mg"
    assert item["dosage_form"] == "Viên nén"
    assert item["has_active_ingredients"] is True
    assert 0.7 <= item["score"] <= 1 and round(item["score"], 3) == item["score"]


def test_soft_deleted_never_candidate__AC5(client, make, auth, db, tag):
    live = add_med(db, make, f"Amlodipin {tag}", "5 mg")
    gone = add_med(db, make, f"Amlodipin {tag}", "5 mg", deleted=True)
    fuzzy_gone = add_med(db, make, f"Panadol{tag}", "500 mg", deleted=True)
    headers = auth(make.user())

    exact = ok(match(client, headers, {"text": f"AMLODIPIN {tag}\n5mg"}))
    assert live in item_ids(exact) and gone not in item_ids(exact)

    misread = ok(match(client, headers, {"text": f"PANAD0L{tag.upper()} 500mg"}))
    assert fuzzy_gone not in item_ids(misread)
    assert misread["status"] == "no_match"


def test_match_issues_only_selects__AC7(client, make, auth, db, tag):
    from drugtime.shared.db import get_engine

    add_med(db, make, f"Cefuroxim {tag}", "500 mg")
    headers = auth(make.user())
    before = db.execute(text("SELECT count(*) FROM medications")).scalar_one()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        sentinel = f"CEFUR0XIM {tag.upper()} 500mg"
        body = ok(match(client, headers, {"text": sentinel}))
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert body["status"] in {"matched", "low_confidence", "no_match"}
    assert statements, "the request must read the catalog"
    lowered_tag = tag.lower()
    for statement, _ in statements:
        sql = statement.strip().upper()
        assert sql.startswith(("SELECT", "WITH", "BEGIN", "COMMIT", "ROLLBACK")), statement
        assert not any(word in sql for word in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE "))
        # OCR text only ever travels as bound parameters, never inside SQL text.
        assert lowered_tag not in statement.lower()
    assert db.execute(text("SELECT count(*) FROM medications")).scalar_one() == before


def test_match_requires_auth_any_role__AC8(client, make, auth, admin_auth, db, tag):
    add_med(db, make, f"Losartan {tag}", "50 mg")
    payload = {"text": f"LOSARTAN {tag} 50mg"}
    assert client.post(PATH, json=payload).status_code == 401
    bad = client.post(PATH, json=payload, headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401
    assert ok(match(client, auth(make.user()), payload))["items"]
    _, admin_headers = admin_auth
    assert ok(match(client, admin_headers, payload))["items"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": " \n\t "},
        {"text": "x" * 2001},
        {"text": "Panadol", "limit": 0},
        {"text": "Panadol", "limit": 11},
        {"text": "Panadol", "limit": "5x"},
        {"text": "Panadol", "patient_id": "00000000-0000-0000-0000-000000000000"},
        {"text": 123},
    ],
)
def test_invalid_body_422__AC9(client, make, auth, body):
    r = match(client, auth(make.user()), body)
    assert r.status_code == 422, r.text
    assert r.headers["cache-control"] == "no-store"
    assert isinstance(r.json()["detail"], list)


def test_boundary_body_accepted__AC9(client, make, auth, db, tag):
    add_med(db, make, f"Metformin {tag}", "850 mg")
    headers = auth(make.user())
    long_text = (f"METFORMIN {tag} 850mg\n" * 200)[:2000]
    assert len(long_text) == 2000
    assert ok(match(client, headers, {"text": long_text, "limit": 10}))
    assert len(ok(match(client, headers, {"text": f"Metformin {tag}", "limit": 1}))["items"]) <= 1


def test_newlines_preserved_votes__AC16(client, make, auth, db, tag):
    mid = add_med(db, make, f"Glucophage {tag}", "850 mg")
    headers = auth(make.user())
    lines = [f"GLUCOPHAGE {tag}", "850mg", f"Glucophage {tag}", "HSD 12/2027"]
    lf = ok(match(client, headers, {"text": "\n".join(lines)}))
    crlf = ok(match(client, headers, {"text": "\r\n".join(lines)}))
    assert lf == crlf
    assert lf["status"] == "matched" and lf["preselected_id"] == mid
    # Line breaks reach 4.12 intact: the suggested query is the name line alone, while on
    # one line the expiry date pollutes it. (adhoc-20261106: name scores are word coverage,
    # so a score difference no longer shows the line breaks.)
    unknown = [f"XYLOQUANT {tag}", "HSD 12/2027"]
    for separator in ("\n", "\r\n"):
        body = ok(match(client, headers, {"text": separator.join(unknown)}))
        assert body["suggested_query"] == f"xyloquant {tag}"
    joined = ok(match(client, headers, {"text": " ".join(unknown)}))
    assert joined["suggested_query"] == f"xyloquant {tag} hsd 12/2027"


def test_fuzzy_finds_misread_name__AC17(client, make, auth, db, tag):
    mid = add_med(db, make, f"Panadol{tag}", "500 mg")
    headers = auth(make.user())
    # "0" for "o": no substring hit in any 4.12 kind, only the trigram fallback finds it.
    body = ok(match(client, headers, {"text": f"PANAD0L{tag.upper()}"}))
    assert mid in item_ids(body)
    assert body["status"] != "matched" or body["preselected_id"] == mid


def test_strength_mismatch_no_match_with_query__AC18(client, make, auth, db, tag):
    mid = add_med(db, make, f"Hapacol {tag}", "250 mg")
    body = ok(match(client, auth(make.user()), {"text": f"HAPACOL {tag}\n500 mg"}))
    assert body["status"] == "no_match"
    assert body["items"] == [] and mid not in item_ids(body)
    assert body["reasons"] == ["strength_mismatch"]
    assert body["suggested_query"] == f"hapacol {tag}"


def test_tie_group_returned_whole__B1(client, make, auth, db, tag):
    ids = sorted(add_med(db, make, f"Cefuroxim {tag}", "500 mg") for _ in range(3))
    body = ok(match(client, auth(make.user()), {"text": f"CEFUROXIM {tag} 500mg"}))
    assert body["status"] == "matched"
    assert item_ids(body) == ids and body["preselected_id"] == ids[0]
    assert "tie" in body["reasons"]


def test_ingredient_line_does_not_preselect_other_product__D2(client, make, auth, db, tag):
    """Found by the AC11 bench on the real catalog (05-test-report, BUG-01).

    The brand name is misread, and the ingredient line names a generic product exactly.
    `matched` would preselect a different catalog product than the one being scanned
    (QD-39: never assign a near-identical medicine). Expected: not matched to the generic.
    """
    brand = add_med(db, make, f"Konlemax{tag}", "50 mg", ingredient=f"Diacerein{tag}")
    generic = add_med(db, make, f"Diacerein{tag}", "50 mg", ingredient=f"Diacerein{tag}")
    body = ok(
        match(client, auth(make.user()), {"text": f"KONLCMAX{tag.upper()}\nDiacerein{tag} 50mg"})
    )
    assert not (body["status"] == "matched" and body["preselected_id"] == generic), body
    assert brand in item_ids(body) or body["status"] != "matched"


# --- adhoc-20261106: brand vs active-ingredient evidence on PostgreSQL ---


def test_brand_ranks_above_generic_named_with_probe_cut__AC1(client, make, auth, db, tag):
    """201 generic-named rows with lower ids push the brand out of the ingredient lookup
    (LIMIT 200 by id, sql_catalog.find_ocr_matches); the brand must still rank first."""
    db.execute(
        text(
            "INSERT INTO medications (name, raw_active_ingredient, strength_text, dosage_form) "
            "SELECT :n, :ai, '500 mg', 'Viên nén' FROM generate_series(1, 201)"
        ),
        {"n": f"Paracetamol{tag} 500mg", "ai": f"Paracetamol{tag}"},
    )
    brand = add_med(db, make, f"Efferalgan{tag}", "500 mg", ingredient=f"Paracetamol{tag}")
    body = ok(
        match(
            client,
            auth(make.user()),
            {"text": f"EFFERALGAN{tag.upper()}\nParacetamol{tag} 500mg"},
        )
    )
    assert body["items"][0]["id"] == brand, body


def test_combination_null_strength_brand_first__AC2(client, make, auth, db, tag):
    brand = add_med(
        db, make, f"Tiffy Dey{tag}", None,
        ingredient=f"Paracetamol{tag} 500mg; Chlorpheniramin{tag} 2mg",
    )
    generic = add_med(db, make, f"Paracetamol{tag} 500mg", "500 mg", ingredient=f"Paracetamol{tag}")
    body = ok(
        match(
            client,
            auth(make.user()),
            {
                "text": f"TIFFY DEY{tag.upper()}\nParacetamol{tag} 500mg\n"
                f"Chlorpheniramin{tag} 2mg"
            },
        )
    )
    assert body["items"][0]["id"] == brand, body
    assert body["preselected_id"] != generic


def test_two_line_brand_name__AC3(client, make, auth, db, tag):
    # Both words carry the tag: "original" alone hits unrelated catalog rows.
    original = add_med(db, make, f"Strepsils{tag} Original{tag}", None, ingredient=None)
    add_med(db, make, f"Strepsils{tag} Cool{tag}", None, ingredient=None)
    body = ok(match(client, auth(make.user()), {"text": f"Strepsils{tag}\nOriginal{tag}"}))
    assert body["items"][0]["id"] == original, body


def test_generic_top_with_cut_ingredient_lookup_not_matched__AC7(client, make, auth, db, tag):
    """C4 on PostgreSQL: the brand line is unreadable ("APO1ETS…" has no 4-letter run) and
    201 generic rows push the brand of the same ingredient out of the ingredient lookup.
    The generic must never be preselected (QD-39)."""
    db.execute(
        text(
            "INSERT INTO medications (name, raw_active_ingredient, strength_text, dosage_form) "
            "SELECT :n, :ai, '75 mg', 'Viên nén' FROM generate_series(1, 201)"
        ),
        {"n": f"Clopidogrel{tag} 75mg", "ai": f"Clopidogrel{tag}"},
    )
    add_med(db, make, f"Apolets{tag}", "75 mg", ingredient=f"Clopidogrel{tag}")
    body = ok(
        match(client, auth(make.user()), {"text": f"APO1ETS 75\nClopidogrel{tag} 75mg"})
    )
    assert body["status"] != "matched" and body["preselected_id"] is None, body
    assert "truncated" in body["reasons"]
