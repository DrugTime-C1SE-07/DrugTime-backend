from dataclasses import dataclass


@dataclass(frozen=True)
class Allergen:
    id: str
    category: str
    name: str


ALLERGENS = (
    Allergen("penicillin", "drug", "Penicillin"),
    Allergen("aspirin", "drug", "Aspirin"),
    Allergen("sulfa", "drug", "Sulfa"),
    Allergen("cephalosporin", "drug", "Cephalosporin"),
    Allergen("seafood", "food", "Hải sản"),
    Allergen("peanuts", "food", "Đậu phộng"),
    Allergen("eggs", "food", "Trứng"),
    Allergen("milk", "food", "Sữa"),
)


def allergen_exists(allergen_id: str) -> bool:
    return any(item.id == allergen_id for item in ALLERGENS)
