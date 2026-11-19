"""The real allergen catalog seed fits the meal-suggestion allergy declaration
(task adhoc-20261118-health-profile-catalog, AC9, AC12; review 06 H1).

Fixtures with short names hid that two seeded names were longer than the 40 characters a
meal-suggestion item allows; this test reads the generated seed itself."""

import re
from pathlib import Path

from drugtime.modules.ai_meal.adapters.inbound.schemas import AllergyDeclaration
from drugtime.modules.medication.domain.health_setup import MAX_ALLERGY_NAME

SEED = Path(__file__).resolve().parents[2] / "supabase/seeds/20_health_profile_catalog.sql"
ROW = re.compile(r"^\s*\('([a-z][a-z0-9_]*)', '(drug|food)', '((?:[^']|'')*)', ", re.M)


def _seeded_allergens() -> dict[str, str]:
    sql = SEED.read_text(encoding="utf-8")
    block = sql.split("INSERT INTO allergens", 1)[1].split("ON CONFLICT", 1)[0]
    return {m.group(1): m.group(3).replace("''", "'") for m in ROW.finditer(block)}


def test_seed_has_allergen_rows():
    allergens = _seeded_allergens()
    count = int(re.search(r"-- count allergens=(\d+)", SEED.read_text(encoding="utf-8"))[1])
    assert len(allergens) == count > 0


def test_every_seeded_allergen_name_fits_meal_item_limit__AC12():
    too_long = {i: n for i, n in _seeded_allergens().items() if len(n) > MAX_ALLERGY_NAME}
    assert too_long == {}


def test_whole_catalog_plus_30_custom_names_is_a_valid_declaration__AC9():
    names = list(_seeded_allergens().values())
    custom = [f"Tự nhập {i}" for i in range(30)]
    declaration = AllergyDeclaration(none=False, items=names + custom)
    assert len(declaration.items) == len(names) + 30
