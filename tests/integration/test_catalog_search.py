"""Catalog search and GET /medications/search alias (brainstorm-medications-search).

Mỗi test dùng một tiền tố ngẫu nhiên trong tên thuốc để không đụng dữ liệu test khác trong
cùng DB (danh mục dùng chung).
"""

from uuid import uuid4

import pytest


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
    user = make.user()
    make.catalog_medication(name=f"B chứa {tag}")
    make.catalog_medication(name=f"A chứa {tag}")
    make.catalog_medication(name=f"{tag} Z bắt đầu")
    make.catalog_medication(name=f"{tag} Y bắt đầu")

    assert _names(_search(client, auth, user, search_path, tag)) == [
        f"{tag} Y bắt đầu",
        f"{tag} Z bắt đầu",
        f"A chứa {tag}",
        f"B chứa {tag}",
    ]


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
    # '%' và '_' đứng một mình không khớp mọi thứ.
    assert all("%" in n for n in _names(_search(client, auth, user, search_path, "%", limit=50)))
    assert all("_" in n for n in _names(_search(client, auth, user, search_path, "_", limit=50)))


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


def test_internal_whitespace_is_preserved__AC4(client, make, auth, tag, search_path):
    user = make.user()
    make.catalog_medication(name=f"{tag} Thuốc ho")
    assert _names(_search(client, auth, user, search_path, f"{tag} thuoc ho")) == [
        f"{tag} Thuốc ho"
    ]
    assert _names(_search(client, auth, user, search_path, f"{tag} thuoc  ho")) == []


def test_invalid_token_is_rejected__AC2(client, search_path):
    response = client.get(
        search_path, params={"q": "amlo"}, headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
