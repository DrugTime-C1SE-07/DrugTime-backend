"""Pure normalization of external medication records."""

import re
import unicodedata
from dataclasses import dataclass


_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedMedication:
    source_ref: str
    name: str
    raw_active_ingredient: str | None = None
    strength_text: str | None = None
    dosage_form: str | None = None
    manufacturer_name: str | None = None
    manufacturer_country: str | None = None
    packaging_spec: str | None = None
    withdrawn: bool = False


def normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFC", str(value))
    text = _SPACE.sub(" ", text).strip()
    return text or None


def normalize_record(record: dict[str, object]) -> NormalizedMedication:
    """Normalize a canonical raw record produced by a source parser."""
    values = {name: normalize_text(record.get(name)) for name in NormalizedMedication.__annotations__}
    source_ref = values.get("source_ref")
    name = values.get("name")
    if not source_ref or not name:
        raise ValueError("catalog row requires source_ref and name")
    return NormalizedMedication(
        source_ref=source_ref,
        name=name,
        raw_active_ingredient=values.get("raw_active_ingredient"),
        strength_text=values.get("strength_text"),
        dosage_form=values.get("dosage_form"),
        manufacturer_name=values.get("manufacturer_name"),
        manufacturer_country=values.get("manufacturer_country"),
        packaging_spec=values.get("packaging_spec"),
        withdrawn=record.get("withdrawn") is True,
    )
