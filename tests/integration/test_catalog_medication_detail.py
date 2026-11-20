"""GET /catalog/medications/{id} với DB thật (adhoc-20261120-add-medication-ux, AC16, AC17).

Danh mục không phải dữ liệu sức khỏe: không kiểm consent, không ghi access_logs.
"""

from sqlalchemy import text

FIELDS = {
    "id",
    "name",
    "active_ingredient",
    "strength_text",
    "dosage_form",
    "manufacturer_name",
    "manufacturer_country",
    "packaging_spec",
    "source",
}


def _set(db, med_id, **cols):
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    db.execute(text(f"UPDATE medications SET {sets} WHERE id = :id"), {"id": med_id, **cols})


def test_full_detail_matches_contract__AC16(client, make, auth, db):
    user = make.user()
    med = make.catalog_medication(name="Amlodipin 5mg", active_ingredient="Amlodipin besilat")
    _set(
        db,
        med,
        manufacturer_name="Công ty CP Dược phẩm ABC",
        manufacturer_country="Việt Nam",
        packaging_spec="Hộp 3 vỉ x 10 viên",
        source="dav_drugbank",
        source_ref=f"test-{med}",
    )
    r = client.get(f"/catalog/medications/{med}", headers=auth(user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == FIELDS
    assert body == {
        "id": med,
        "name": "Amlodipin 5mg",
        "active_ingredient": "Amlodipin besilat",
        "strength_text": "5 mg",
        "dosage_form": "Viên nén",
        "manufacturer_name": "Công ty CP Dược phẩm ABC",
        "manufacturer_country": "Việt Nam",
        "packaging_spec": "Hộp 3 vỉ x 10 viên",
        "source": "dav_drugbank",
    }


def test_missing_fields_are_null_and_strength_is_raw__AC16(client, make, auth, db):
    user = make.user()
    med = make.catalog_medication(dosage_form=None)
    _set(db, med, strength_text="0,04")
    body = client.get(f"/catalog/medications/{med}", headers=auth(user)).json()
    assert body["strength_text"] == "0,04"  # không chuẩn hóa hay quy đổi (QD-38)
    for field in (
        "active_ingredient",
        "dosage_form",
        "manufacturer_name",
        "manufacturer_country",
        "packaging_spec",
        "source",
    ):
        assert body[field] is None, field


def test_soft_deleted_entry_still_returned__AC16_QD36(client, make, auth):
    user = make.user()
    med = make.catalog_medication(deleted=True)
    r = client.get(f"/catalog/medications/{med}", headers=auth(user))
    assert r.status_code == 200
    assert r.json()["id"] == med


def test_unknown_id_404__AC17(client, make, auth, db):
    user = make.user()
    missing = db.execute(text("SELECT coalesce(max(id), 0) + 1000 FROM medications")).scalar_one()
    r = client.get(f"/catalog/medications/{missing}", headers=auth(user))
    assert r.status_code == 404
    assert r.json() == {"detail": "catalog_medication_not_found"}


def test_without_token_401__AC17(client, make):
    med = make.catalog_medication()
    r = client.get(f"/catalog/medications/{med}")
    assert r.status_code == 401


def test_any_session_without_health_consent_can_read_and_no_access_log(client, make, auth):
    """Danh mục không phải dữ liệu sức khỏe: không cần consent, không ghi nhật ký."""
    user = make.user(consents=())
    med = make.catalog_medication()
    assert client.get(f"/catalog/medications/{med}", headers=auth(user)).status_code == 200
    assert make.access_logs(user) == []
