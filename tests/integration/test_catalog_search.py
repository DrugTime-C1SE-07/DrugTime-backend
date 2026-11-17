"""Catalog search and GET /medications/search alias (brainstorm-medications-search).

Mỗi test dùng một tiền tố ngẫu nhiên trong tên thuốc để không đụng dữ liệu test khác trong
cùng DB (danh mục dùng chung).
"""

from uuid import uuid4

import pytest
from sqlalchemy import text


@pytest.fixture(params=["/catalog/medications", "/medications/search"])
def search_path(request):
    return request.param


@pytest.fixture
def tag():
    """Chuỗi chỉ chữ cái, không dấu, duy nhất cho test (trigram cần ≥ 3 ký tự)."""
    return "zq" + "".join(chr(ord("a") + int(c, 16) % 26) for c in uuid4().hex[:8])


def _search(client, auth, user, search_path, q, **params):
    return client.get(search_path, params={"q": q, **params}, headers=auth(user))


def _names(r):
    assert r.status_code == 200, r.text
    return [m["name"] for m in r.json()["items"]]


def test_matches_name_and_ingredient_excludes_deleted_respects_limit__AC5(
    client, make, auth, tag, search_path
):
    user = make.user()
    make.catalog_medication(name=f"Metformin {tag} 500mg", active_ingredient="Metformin HCl")
    make.catalog_medication(name=f"Glucophage {tag}", active_ingredient=f"Metformin {tag}")
    make.catalog_medication(name=f"Metformin {tag} 850mg", deleted=True)
    make.catalog_medication(name=f"Unrelated {uuid4().hex[:6]}")

    r = _search(client, auth, user, search_path, tag)
    items = r.json()["items"]
    assert sorted(_names(r)) == sorted([f"Metformin {tag} 500mg", f"Glucophage {tag}"])
    assert all(
        set(m) == {"id", "name", "active_ingredient", "strength_text", "dosage_form"} for m in items
    )
    by_name = {m["name"]: m for m in items}
    assert by_name[f"Metformin {tag} 500mg"]["active_ingredient"] == "Metformin HCl"

    assert len(_search(client, auth, user, search_path, tag, limit=1).json()["items"]) == 1


def test_null_active_ingredient_is_returned_as_null__AC5(client, make, auth, tag, search_path):
    user = make.user()
    make.catalog_medication(name=f"Siro {tag}", active_ingredient=None, dosage_form="Siro")
    item = _search(client, auth, user, search_path, tag).json()["items"][0]
    assert item["active_ingredient"] is None and item["dosage_form"] == "Siro"


def test_unaccented_and_case_insensitive__AC5c(client, make, auth, tag, search_path):
    user = make.user()
    make.catalog_medication(name=f"Thuốc ho Bảo Thanh {tag}")
    make.catalog_medication(name=f"Thuốc bổ {tag}", active_ingredient=f"Đồng sulfat {tag}")

    for q in (
        f"thuoc ho bao thanh {tag}",
        f"THUỐC HO BẢO THANH {tag}",
        f"thuốc ho bảo thanh {tag}",
    ):
        names = _names(_search(client, auth, user, search_path, q))
        assert f"Thuốc ho Bảo Thanh {tag}" in names, q
    names = _names(_search(client, auth, user, search_path, f"dong sulfat {tag}"))
    assert names == [f"Thuốc bổ {tag}"]
    names = _names(_search(client, auth, user, search_path, f"ĐỒNG SULFAT {tag}"))
    assert names == [f"Thuốc bổ {tag}"]


def test_prefix_first_then_name_order__AC5(client, make, auth, tag, search_path):
    """Tên bắt đầu bằng q đứng trước tên chỉ chứa q; trong mỗi nhóm thứ tự theo độ giống rồi
    theo tên (contract adhoc-20261116), nên chỉ kiểm theo nhóm và kiểm bậc cuối riêng."""
    user = make.user()
    make.catalog_medication(name=f"B chứa {tag}")
    make.catalog_medication(name=f"A chứa {tag}")
    make.catalog_medication(name=f"{tag} Z bắt đầu")
    make.catalog_medication(name=f"{tag} Y bắt đầu")

    names = _names(_search(client, auth, user, search_path, tag))
    assert set(names[:2]) == {f"{tag} Y bắt đầu", f"{tag} Z bắt đầu"}
    assert set(names[2:]) == {f"A chứa {tag}", f"B chứa {tag}"}


def test_equal_rank_falls_back_to_name_then_id__AC5(client, make, auth, tag, search_path):
    user = make.user()
    second = make.catalog_medication(name=f"{tag} cùng tên")
    first = make.catalog_medication(name=f"{tag} cùng tên")
    make.catalog_medication(name=f"{tag} cung ten")  # bỏ dấu giống hệt: cùng mọi bậc trừ tên
    r = _search(client, auth, user, search_path, f"{tag} cung ten")
    ids = [m["id"] for m in r.json()["items"] if m["name"] == f"{tag} cùng tên"]
    assert ids == sorted([first, second])
    assert _names(r)[0] == f"{tag} cung ten"  # "cung" < "cùng" theo collation tên


def test_like_wildcards_are_literal__AC6(client, make, auth, tag, search_path):
    user = make.user()
    make.catalog_medication(name=f"{tag} 100% tự nhiên")
    make.catalog_medication(name=f"{tag} a_b")
    make.catalog_medication(name=f"{tag} axb")
    make.catalog_medication(name=f"{tag} a\\b")

    assert _names(_search(client, auth, user, search_path, f"{tag} 100%")) == [
        f"{tag} 100% tự nhiên"
    ]
    assert _names(_search(client, auth, user, search_path, f"{tag} a_b")) == [f"{tag} a_b"]
    assert _names(_search(client, auth, user, search_path, f"{tag} a\\b")) == [f"{tag} a\\b"]
    # '%' và '_' đứng một mình không khớp mọi thứ: mỗi kết quả chứa đúng ký tự đó ở một trường
    # được tìm (tên, hoạt chất hoặc hàm lượng; danh mục thật có '%' trong hoạt chất).
    for ch in ("%", "_"):
        r = _search(client, auth, user, search_path, ch, limit=50)
        assert r.status_code == 200, r.text
        for m in r.json()["items"]:
            fields = (m["name"], m["active_ingredient"] or "", m["strength_text"] or "")
            assert any(ch in f for f in fields), (ch, m)


def test_query_is_trimmed(client, make, auth, tag, search_path):
    user = make.user()
    make.catalog_medication(name=f"Losartan {tag}")
    assert _names(_search(client, auth, user, search_path, f"   {tag}   ")) == [f"Losartan {tag}"]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "a" * 101},
        {"q": "x", "limit": 0},
        {"q": "x", "limit": 51},
        {"q": "x", "limit": "invalid"},
    ],
)
def test_bad_query_422__AC6(client, make, auth, params, search_path):
    user = make.user()
    r = client.get(search_path, params=params, headers=auth(user))
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


def test_requires_auth_401__AC3(client, search_path):
    assert client.get(search_path, params={"q": "amlo"}).status_code == 401


def test_any_valid_session_no_consent_needed_no_log(client, make, auth, tag, search_path):
    """Danh mục không phải dữ liệu sức khỏe: người không có consent vẫn tìm được, không log."""
    user = make.user(consents=())
    make.catalog_medication(name=f"Paracetamol {tag}")
    assert _names(_search(client, auth, user, search_path, tag)) == [f"Paracetamol {tag}"]
    assert make.access_logs(user) == []


def test_alias_matches_catalog_without_id_route_collision__AC1_AC6(client, make, auth, tag):
    user = make.user()
    make.catalog_medication(name=f"{tag} Amlodipin", active_ingredient="Amlodipin")
    make.catalog_medication(name=f"Contains {tag}")
    responses = [
        _search(client, auth, user, path, tag)
        for path in ("/catalog/medications", "/medications/search")
    ]
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json() == responses[1].json()
    assert len(responses[1].json()["items"]) == 2


def test_empty_search_returns_items_empty__AC1(client, make, auth, tag, search_path):
    user = make.user()
    response = _search(client, auth, user, search_path, tag)
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_search_default_and_limit_boundaries__AC1_AC5(client, make, auth, tag, search_path):
    user = make.user()
    for index in range(51):
        make.catalog_medication(name=f"{tag} {index:02d}", with_ingredient=False)
    for params, count in (({}, 20), ({"limit": 1}, 1), ({"limit": 50}, 50)):
        response = _search(client, auth, user, search_path, tag, **params)
        assert _names(response) == [f"{tag} {index:02d}" for index in range(count)]


@pytest.mark.parametrize("length", [1, 100])
def test_query_length_boundaries__AC5(client, make, auth, search_path, length):
    user = make.user()
    response = _search(client, auth, user, search_path, "a" * length, limit=1)
    assert response.status_code == 200
    assert len(response.json()["items"]) <= 1


def test_multiple_spaces_count_as_one__AC14(client, make, auth, tag, search_path):
    """Contract adhoc-20261116: tách theo từ, nhiều khoảng trắng như một."""
    user = make.user()
    make.catalog_medication(name=f"{tag} Thuốc ho")
    for q in (f"{tag} thuoc ho", f"{tag} thuoc  ho", f"  {tag}	THUỐC   ho "):
        assert _names(_search(client, auth, user, search_path, q)) == [f"{tag} Thuốc ho"], q


def _strength(db, mid, value):
    db.execute(
        text("UPDATE medications SET strength_text = :s WHERE id = :id"), {"s": value, "id": mid}
    )


def test_ingredient_and_strength_words_match_brand_row__AC12(
    client, make, auth, tag, db, search_path
):
    """ "metformin 500 mg": hoạt chất + hàm lượng khớp dòng nhãn hiệu mà tên không chứa
    hoạt chất; hàm lượng khác không khớp; "500 mg" = "500mg"."""
    user = make.user()
    brand = make.catalog_medication(
        name=f"Glucophage{tag} 500 mg", active_ingredient=f"Metformin{tag} hydroclorid"
    )
    _strength(db, brand, "500 mg")
    other = make.catalog_medication(
        name=f"Metformin{tag} Stada 850mg", active_ingredient=f"Metformin{tag}"
    )
    _strength(db, other, "850mg")
    joined = make.catalog_medication(
        name=f"Gluphakaps{tag}", active_ingredient=f"Metformin{tag} HCl"
    )
    _strength(db, joined, "500mg")

    for q in (f"metformin{tag} 500 mg", f"Metformin{tag} 500MG", f"metformin{tag}  500 mg"):
        names = _names(_search(client, auth, user, search_path, q))
        assert sorted(names) == sorted([f"Glucophage{tag} 500 mg", f"Gluphakaps{tag}"]), q


def test_brand_word_and_number_ranks_brand_first__AC12(client, make, auth, tag, db, search_path):
    user = make.user()
    target = make.catalog_medication(
        name=f"Glucophage{tag} XR 500 mg", active_ingredient="Metformin"
    )
    _strength(db, target, "500 mg")
    for s in ["850 mg", "1000 mg"]:
        mid = make.catalog_medication(name=f"Glucophage{tag} {s}", active_ingredient="Metformin")
        _strength(db, mid, s)
    # Dòng chỉ có số 500 trong tên của thuốc khác không được vượt lên.
    make.catalog_medication(name=f"Zz {tag} 500", active_ingredient=f"Glucophage{tag}")

    names = _names(_search(client, auth, user, search_path, f"glucophage{tag} 500"))
    assert names[0] == f"Glucophage{tag} XR 500 mg"
    assert f"Glucophage{tag} 850 mg" not in names


def test_number_word_matches_strength_and_name_without_spaces__AC12(
    client, make, auth, tag, db, search_path
):
    user = make.user()
    in_strength = make.catalog_medication(name=f"Panfor{tag} PR", active_ingredient="Metformin")
    _strength(db, in_strength, "500 mg")
    in_name = make.catalog_medication(name=f"Panfor{tag} 500 mg", active_ingredient="Metformin")
    _strength(db, in_name, None)
    names = _names(_search(client, auth, user, search_path, f"panfor{tag} 500mg"))
    assert sorted(names) == sorted([f"Panfor{tag} PR", f"Panfor{tag} 500 mg"])


def test_invalid_token_is_rejected__AC2(client, search_path):
    response = client.get(
        search_path, params={"q": "amlo"}, headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_letter_word_also_matches_strength_text__AC12(client, make, auth, tag, db, search_path):
    """Contract: mỗi từ, kể cả từ không có chữ số, có thể nằm ở hàm lượng."""
    user = make.user()
    mid = make.catalog_medication(name=f"Axore{tag}", active_ingredient="Atorvastatin Calcium")
    _strength(db, mid, "Atorvastatin 20mg/ viên")
    assert _names(_search(client, auth, user, search_path, f"axore{tag} 20mg vien")) == [
        f"Axore{tag}"
    ]
