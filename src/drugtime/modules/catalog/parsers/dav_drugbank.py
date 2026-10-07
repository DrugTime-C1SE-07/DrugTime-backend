"""Pure parser for DAV's public registration JSON response."""

import json
from typing import Any


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse(payload: bytes) -> list[dict[str, object]]:
    """Convert one DAV API page to canonical raw medication dictionaries."""
    document = json.loads(payload)
    result = _object(document.get("result")) if isinstance(document, dict) else {}
    items = result.get("items")
    if not isinstance(items, list):
        raise ValueError("DAV response does not contain result.items")

    rows: list[dict[str, object]] = []
    for value in items:
        item = _object(value)
        medicine = _object(item.get("thongTinThuocCoBan"))
        manufacturer = _object(item.get("congTySanXuat"))
        rows.append(
            {
                "source_ref": item.get("soDangKy"),
                "name": item.get("tenThuoc"),
                "raw_active_ingredient": medicine.get("hoatChatChinh"),
                "strength_text": medicine.get("hamLuong"),
                "dosage_form": medicine.get("dangBaoChe"),
                "manufacturer_name": manufacturer.get("tenCongTySanXuat"),
                "manufacturer_country": manufacturer.get("nuocSanXuat"),
                "packaging_spec": medicine.get("dongGoi"),
                "withdrawn": item.get("isDaRutSoDangKy") is True,
            }
        )
    return rows
