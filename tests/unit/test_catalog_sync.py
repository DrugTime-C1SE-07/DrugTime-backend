from drugtime.modules.catalog.normalize import normalize_record
from drugtime.modules.catalog.parsers.dav_drugbank import parse


def test_dav_parser_returns_rows_without_network_access():
    payload = b"""{"result":{"totalCount":1,"items":[{
      "soDangKy":"VD-1","tenThuoc":"Medicine A",
      "thongTinThuocCoBan":{"hoatChatChinh":"Ingredient","hamLuong":"10 mg",
        "dangBaoChe":"Tablet","dongGoi":"Box"},
      "congTySanXuat":{"tenCongTySanXuat":"Maker","nuocSanXuat":"VN"},
      "isDaRutSoDangKy":false}]}}"""

    assert parse(payload) == [
        {
            "source_ref": "VD-1",
            "name": "Medicine A",
            "raw_active_ingredient": "Ingredient",
            "strength_text": "10 mg",
            "dosage_form": "Tablet",
            "manufacturer_name": "Maker",
            "manufacturer_country": "VN",
            "packaging_spec": "Box",
            "withdrawn": False,
        }
    ]


def test_normalize_record_cleans_canonical_fields():
    result = normalize_record(
        {"source_ref": " VD-1 ", "name": " Medicine   A "},
    )

    assert result.source_ref == "VD-1"
    assert result.name == "Medicine A"
