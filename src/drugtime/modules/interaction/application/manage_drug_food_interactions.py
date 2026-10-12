"""Quy tắc tương tác giữa hoạt chất và thực phẩm (task 2.16)."""

from drugtime.modules.interaction.application.manage_rules import RuleService
from drugtime.modules.interaction.application.ports import (
    AdminDirectory,
    IngredientCatalog,
    RuleStore,
)
from drugtime.modules.interaction.domain.catalog_rules import (
    DrugFoodInteractionContent,
    validate_drug_food_interaction,
)


def drug_food_interaction_service(
    store: RuleStore[DrugFoodInteractionContent],
    ingredients: IngredientCatalog,
    admins: AdminDirectory,
) -> RuleService[DrugFoodInteractionContent]:
    return RuleService(store, ingredients, admins, validate_drug_food_interaction)
