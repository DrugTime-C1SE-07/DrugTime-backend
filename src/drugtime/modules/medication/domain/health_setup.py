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
class HealthSetup:
    revision: str
    allergies: SetupStep[str]
    conditions: SetupStep[int]


def normalize_custom_names(names: tuple[str, ...]) -> tuple[str, ...]:
    normalized = [normalize("NFC", name.strip()) for name in names]
    if any(not name or "\x00" in name or len(name) > 120 for name in normalized):
        raise DomainError("invalid_custom_name")
    if len({name.casefold() for name in normalized}) != len(normalized):
        raise DomainError("duplicate_custom_name")
    return tuple(sorted(normalized))
