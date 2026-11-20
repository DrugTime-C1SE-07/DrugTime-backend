from dataclasses import dataclass
from typing import Literal
from unicodedata import normalize

from drugtime.shared.errors import DomainError


@dataclass(frozen=True)
class SetupStep[CatalogId: (int, str)]:
    status: Literal["unreported", "none_known", "reported"]
    catalog_ids: tuple[CatalogId, ...] = ()
    custom_names: tuple[str, ...] = ()

    @classmethod
    def from_values(cls, none_known, catalog_ids, custom_names):
        if none_known:
            return cls("none_known")
        if catalog_ids or custom_names:
            return cls("reported", tuple(sorted(catalog_ids)), tuple(sorted(custom_names)))
        return cls("unreported")


@dataclass(frozen=True)
class AllergenLabel:
    """Catalog label of a stored allergen id, retired catalog entries included."""

    id: str
    category: str
    name: str


@dataclass(frozen=True)
class HealthSetup:
    revision: str
    allergies: SetupStep[str]
    # Chronic diseases only (category chronic_disease) plus custom names.
    conditions: SetupStep[int]
    # Pregnancy, breastfeeding (category physiological_state); catalog-only, no custom names.
    physiological_states: SetupStep[int] = SetupStep("unreported")


# Custom allergy names are sent unchanged to meal suggestions, whose items are <= 40 chars.
MAX_ALLERGY_NAME = 40
MAX_CONDITION_NAME = 120


def normalize_custom_names(names: tuple[str, ...], max_length: int) -> tuple[str, ...]:
    normalized = [normalize("NFC", name.strip()) for name in names]
    if any(not name or "\x00" in name or len(name) > max_length for name in normalized):
        raise DomainError("invalid_custom_name")
    if len({name.casefold() for name in normalized}) != len(normalized):
        raise DomainError("duplicate_custom_name")
    return tuple(sorted(normalized))
