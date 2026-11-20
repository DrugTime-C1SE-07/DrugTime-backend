from dataclasses import dataclass


@dataclass(frozen=True)
class Allergen:
    """Entry of the shared allergen catalog (table `allergens`).

    Entries are never deleted; a retired entry has `is_active = False` and keeps its label for
    profiles that already chose it.
    """

    id: str
    category: str
    name: str
    display_order: int
    is_active: bool
