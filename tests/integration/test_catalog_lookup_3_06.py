"""SCRUM-167 / SCRUM-168: Integration tests for GET /catalog/medications lookup.

Bao gồm:
- Chuẩn hóa từ khóa và tìm kiếm không dấu / hoa-thường / strip hai đầu (SCRUM-167).
- AC4: Khoảng trắng giữa chuỗi được giữ nguyên (truy vấn 2 khoảng trắng không khớp 1 khoảng trắng).
- Khớp chuỗi con liên tục theo LIKE trigram (SCRUM-167).
- Loại trừ thuốc đã xóa mềm (deleted_at IS NOT NULL) khi truy vấn đúng tên (SCRUM-167).
- Kiểm tra hợp lệ query `q` (rỗng/chỉ trắng -> 422, 1 ký tự -> 200 theo quyết định (1)) (SCRUM-168).
- Giới hạn phân trang: mặc định 20, limit=3, limit=50, limit=0 -> 422, limit=51 -> 422 (SCRUM-168).
- Kiểm tra tầng SQL unaccent: SELECT public.catalog_search_key(:s) (SCRUM-166).
"""

import unicodedata
from uuid import uuid4

import pytest
from sqlalchemy import text


@pytest.fixture
def tag():
    """Chuỗi chỉ chữ cái, không dấu, duy nhất cho test (trigram cần >= 3 ký tự)."""
    return "t306" + "".join(chr(ord("a") + int(c, 16) % 26) for c in uuid4().hex[:8])


@pytest.mark.parametrize(
    "input_val, expected",
    [
        ("Thuốc ho Bảo Thanh", "thuoc ho bao thanh"),
        ("Đồng sulfat", "dong sulfat"),
        ("đông", "dong"),
        ("PARACETAMOL", "paracetamol"),
        (unicodedata.normalize("NFD", "Thuốc ho Bảo Thanh"), "thuoc ho bao thanh"),
        (unicodedata.normalize("NFC", "Thuốc ho Bảo Thanh"), "thuoc ho bao thanh"),
        (unicodedata.normalize("NFD", "Đồng"), "dong"),
        (unicodedata.normalize("NFC", "Đồng"), "dong"),
    ],
)
def test_sql_catalog_search_key_unaccent_and_casing(db, input_val, expected):
    """SCRUM-166: Bước bỏ dấu nằm ở SQL: SELECT public.catalog_search_key(:s) xử lý unaccent, đ/Đ -> d, chữ thường."""
    res = db.execute(text("SELECT public.catalog_search_key(:s)"), {"s": input_val}).scalar_one()
    assert res == expected


def test_seed_paracetamol_queries_match_id__SCRUM_167(client, make, auth, tag):
    """Seed 'Paracetamol' với tag ở đầu tên thuốc:
    f'{tag} Paracetamol 500mg'
    - 'tag paracetamol', 'tag Paracetamol', 'tag para', '  tag Paracetamol  ' đều trả đúng thuốc (assert ID cụ thể).
    - AC4: Khoảng trắng giữa chuỗi được giữ nguyên: 'tag  paracetamol' (2 khoảng trắng) không khớp thuốc (trả về rỗng).
    """
    user = make.user()
    med_id = make.catalog_medication(
        name=f"{tag} Paracetamol 500mg",
        active_ingredient=f"{tag} Paracetamol",
    )

    # Các truy vấn khớp chuỗi con liên tục:
    # 1. chữ thường
    # 2. chữ hoa
    # 3. tiền tố của từ tiếp theo
    # 4. có khoảng trắng thừa ở 2 đầu (được strip)
    matching_queries = [
        f"{tag} paracetamol",
        f"{tag} Paracetamol",
        f"{tag} para",
        f"  {tag} Paracetamol  ",
    ]
    for q in matching_queries:
        r = client.get("/catalog/medications", params={"q": q}, headers=auth(user))
        assert r.status_code == 200, f"Query '{q}' failed with status {r.status_code}: {r.text}"
        items = r.json()["items"]
        item_ids = [m["id"] for m in items]
        assert med_id in item_ids, f"Expected med_id {med_id} in {item_ids} for query '{q}'"

    # AC4: Khẳng định khoảng trắng giữa chuỗi KHÔNG gộp.
    # f"{tag}  paracetamol" (2 khoảng trắng giữa) không khớp "{tag} Paracetamol 500mg" (1 khoảng trắng)
    r_double_space = client.get(
        "/catalog/medications",
        params={"q": f"{tag}  paracetamol"},
        headers=auth(user),
    )
    assert r_double_space.status_code == 200, r_double_space.text
    double_space_items = r_double_space.json()["items"]
    double_space_ids = [m["id"] for m in double_space_items]
    assert med_id not in double_space_ids, (
        f"AC4 violation: query with 2 internal spaces '{tag}  paracetamol' "
        f"unexpectedly matched medication {med_id}"
    )


def test_soft_deleted_medication_excluded_when_queried_by_exact_name__SCRUM_167(
    client, make, auth, tag
):
    """Thuốc deleted_at NOT NULL bị loại khi truy vấn ĐÚNG tên nó; đối chứng bản chưa xóa vẫn xuất hiện."""
    user = make.user()
    exact_deleted_name = f"{tag} Paracetamol Deleted"
    deleted_id = make.catalog_medication(name=exact_deleted_name, deleted=True)

    exact_active_name = f"{tag} Paracetamol Active"
    active_id = make.catalog_medication(name=exact_active_name, deleted=False)

    # Truy vấn đúng tên thuốc đã xóa -> không xuất hiện trong kết quả
    r_del = client.get(
        "/catalog/medications", params={"q": exact_deleted_name}, headers=auth(user)
    )
    assert r_del.status_code == 200, r_del.text
    deleted_items = r_del.json()["items"]
    deleted_ids = [m["id"] for m in deleted_items]
    assert deleted_id not in deleted_ids, f"Deleted medication {deleted_id} was unexpectedly returned"

    # Truy vấn bản đối chứng chưa xóa -> xuất hiện
    r_act = client.get(
        "/catalog/medications", params={"q": exact_active_name}, headers=auth(user)
    )
    assert r_act.status_code == 200, r_act.text
    active_items = r_act.json()["items"]
    active_ids = [m["id"] for m in active_items]
    assert active_id in active_ids, f"Active medication {active_id} was not returned"


@pytest.mark.parametrize("blank_q", ["", "   ", " \t \n "])
def test_empty_or_whitespace_only_q_returns_422__SCRUM_168(client, make, auth, blank_q):
    """q rỗng và chỉ khoảng trắng -> 422, assert detail có cấu trúc (loc chứa 'q')."""
    user = make.user()
    r = client.get("/catalog/medications", params={"q": blank_q}, headers=auth(user))
    assert r.status_code == 422, f"Expected 422 for blank query {blank_q!r}, got {r.status_code}"
    body = r.json()
    assert "detail" in body
    assert isinstance(body["detail"], list)
    locs = [item.get("loc", []) for item in body["detail"] if isinstance(item, dict)]
    assert any("q" in loc for loc in locs), f"Expected 'q' in error locs: {locs}"


def test_single_character_q_returns_200__SCRUM_168(client, make, auth):
    """Quyết định (1): Route GIỮ NGUYÊN: q 1 ký tự hợp lệ (200). KHÔNG có test '1 ký tự -> 422'."""
    user = make.user()
    r = client.get("/catalog/medications", params={"q": "a"}, headers=auth(user))
    assert r.status_code == 200, f"Expected 200 for 1-char q, got {r.status_code}: {r.text}"
    assert "items" in r.json()


def test_pagination_and_limit_boundaries__SCRUM_168(client, make, auth, tag):
    """Seed > 20 bản ghi cùng tag:
    - không gửi limit -> đúng 20
    - limit=3 -> đúng 3
    - limit=50 -> hợp lệ (200), trả về toàn bộ 25 bản ghi đã seed
    - limit=51 và limit=0 -> 422 (FastAPI Query(ge=1, le=50) chặn bằng RequestValidationError)
    """
    user = make.user()
    for i in range(25):
        make.catalog_medication(name=f"{tag} Medication {i:02d}")

    # 1. Không gửi limit -> mặc định 20
    r_default = client.get("/catalog/medications", params={"q": tag}, headers=auth(user))
    assert r_default.status_code == 200, r_default.text
    assert len(r_default.json()["items"]) == 20

    # 2. limit=3 -> đúng 3
    r_limit3 = client.get(
        "/catalog/medications", params={"q": tag, "limit": 3}, headers=auth(user)
    )
    assert r_limit3.status_code == 200, r_limit3.text
    assert len(r_limit3.json()["items"]) == 3

    # 3. limit=50 hợp lệ, trả toàn bộ 25 bản ghi
    r_limit50 = client.get(
        "/catalog/medications", params={"q": tag, "limit": 50}, headers=auth(user)
    )
    assert r_limit50.status_code == 200, r_limit50.text
    assert len(r_limit50.json()["items"]) == 25

    # 4. limit=0 -> 422
    r_limit0 = client.get(
        "/catalog/medications", params={"q": tag, "limit": 0}, headers=auth(user)
    )
    assert r_limit0.status_code == 422
    locs0 = [item.get("loc", []) for item in r_limit0.json().get("detail", []) if isinstance(item, dict)]
    assert any("limit" in loc for loc in locs0)

    # 5. limit=51 -> 422
    r_limit51 = client.get(
        "/catalog/medications", params={"q": tag, "limit": 51}, headers=auth(user)
    )
    assert r_limit51.status_code == 422
    locs51 = [item.get("loc", []) for item in r_limit51.json().get("detail", []) if isinstance(item, dict)]
    assert any("limit" in loc for loc in locs51)


def test_unaccented_query_matches_accented_medication__SCRUM_167(client, make, auth, tag):
    """Bỏ dấu và hoa/thường ở SQL catalog_search_key, kiểm tra ở mức API GET /catalog/medications.

    - Truy vấn không dấu ('thuoc ho bao thanh') khớp thuốc có dấu ('Thuốc ho Bảo Thanh').
    - Truy vấn có dấu ('Thuốc ho') cũng khớp đúng thuốc đó.
    - Truy vấn đ/Đ ('dau dau') khớp thuốc có đ ('Đau đầu').
    """
    user = make.user()

    # 1. Thuốc có dấu tiếng Việt: "Thuốc ho Bảo Thanh"
    med_ho_id = make.catalog_medication(name=f"{tag} Thuốc ho Bảo Thanh")

    # Truy vấn không dấu:
    r_unaccented = client.get(
        "/catalog/medications",
        params={"q": f"{tag} thuoc ho bao thanh"},
        headers=auth(user),
    )
    assert r_unaccented.status_code == 200, r_unaccented.text
    ho_unaccented_ids = [m["id"] for m in r_unaccented.json()["items"]]
    assert med_ho_id in ho_unaccented_ids, (
        f"Expected med_ho_id {med_ho_id} in {ho_unaccented_ids} for unaccented query '{tag} thuoc ho bao thanh'"
    )

    # Ca đối ngược: truy vấn có dấu:
    r_accented = client.get(
        "/catalog/medications",
        params={"q": f"{tag} Thuốc ho"},
        headers=auth(user),
    )
    assert r_accented.status_code == 200, r_accented.text
    ho_accented_ids = [m["id"] for m in r_accented.json()["items"]]
    assert med_ho_id in ho_accented_ids, (
        f"Expected med_ho_id {med_ho_id} in {ho_accented_ids} for accented query '{tag} Thuốc ho'"
    )

    # 2. Ca đ/Đ: seed "Đau đầu" và truy vấn "dau dau"
    med_dau_id = make.catalog_medication(name=f"{tag} Đau đầu")

    r_d = client.get(
        "/catalog/medications",
        params={"q": f"{tag} dau dau"},
        headers=auth(user),
    )
    assert r_d.status_code == 200, r_d.text
    dau_ids = [m["id"] for m in r_d.json()["items"]]
    assert med_dau_id in dau_ids, (
        f"Expected med_dau_id {med_dau_id} in {dau_ids} for unaccented d query '{tag} dau dau'"
    )

