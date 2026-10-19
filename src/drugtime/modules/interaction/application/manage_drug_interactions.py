"""Quy tắc tương tác giữa hai hoạt chất (task 2.16)."""

from drugtime.modules.interaction.application.manage_rules import RuleService
from drugtime.modules.interaction.application.ports import (
    AdminDirectory,
    IngredientCatalog,
    RuleStore,
)
from drugtime.modules.interaction.domain.catalog_rules import (
    DrugInteractionContent,
    validate_drug_interaction,
)


def drug_interaction_service(
    store: RuleStore[DrugInteractionContent],
    ingredients: IngredientCatalog,
    admins: AdminDirectory,
) -> RuleService[DrugInteractionContent]:
    return RuleService(store, ingredients, admins, validate_drug_interaction)
