from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.medication.application.manage_health_setup import save_setup
from drugtime.modules.medication.domain.health_setup import (
    MAX_ALLERGY_NAME,
    MAX_CONDITION_NAME,
    HealthSetup,
    SetupStep,
    normalize_custom_names,
)
from drugtime.modules.medication.domain.user_condition import (
    ConditionLabel,
    NewUserCondition,
    UserConditionRecord,
)
from drugtime.shared.errors import Conflict, DomainError

# Catalog fixture: 8, 9 chronic diseases; 30 pregnancy, 31 breastfeeding.
CATEGORIES = {
    8: "chronic_disease",
    9: "chronic_disease",
    30: "physiological_state",
    31: "physiological_state",
}


def _catalog():
    catalog = Mock()
    catalog.labels.side_effect = lambda _uow, ids: {
        i: ConditionLabel(f"c{i}", CATEGORIES[i]) for i in ids if i in CATEGORIES
    }
    return catalog


def test_custom_names_normalize_and_reject_duplicate_or_blank():
    assert normalize_custom_names(("  Ha\u0309i sản ",), 120) == ("Hải sản",)
    with pytest.raises(DomainError, match="duplicate_custom_name"):
        normalize_custom_names(("Tôm", " TÔM "), 120)
    with pytest.raises(DomainError, match="invalid_custom_name"):
        normalize_custom_names(("  ",), 120)


@pytest.mark.parametrize(
    ("max_length", "length", "ok"),
    [
        (MAX_ALLERGY_NAME, 40, True),
        (MAX_ALLERGY_NAME, 41, False),
        (MAX_CONDITION_NAME, 120, True),
        (MAX_CONDITION_NAME, 121, False),
    ],
)
def test_custom_name_length_limit__AC12(max_length, length, ok):
    name = "a" * length
    if ok:
        assert normalize_custom_names((name,), max_length) == (name,)
    else:
        with pytest.raises(DomainError, match="invalid_custom_name"):
            normalize_custom_names((name,), max_length)


def test_save_rejects_allergy_name_over_40_but_keeps_condition_limit__AC12():
    uow, store, links, catalog = Mock(), Mock(), Mock(), _catalog()
    links.list.return_value = []
    store.read.return_value = HealthSetup("1", SetupStep("unreported"), SetupStep("unreported"))
    long_allergy = SetupStep("reported", (), ("a" * 41,))
    with pytest.raises(DomainError, match="invalid_custom_name"):
        save_setup(uow, uuid4(), store, links, catalog, "1", long_allergy, None)
    store.save.assert_not_called()

    long_condition = SetupStep("reported", (), ("b" * 41,))
    save_setup(uow, uuid4(), store, links, catalog, "1", None, long_condition)
    store.save.assert_called_once()


def test_save_preserves_existing_link_and_skipped_step():
    user = uuid4()
    uow, store, links, catalog = Mock(), Mock(), Mock(), _catalog()
    link = UserConditionRecord(3, 8, "Type 2", "Recorded")
    links.list.return_value = [link]
    current = HealthSetup("1", SetupStep("none_known"), SetupStep("reported", (8,)))
    store.read.return_value = current
    store.save.return_value = "2"
    after = save_setup(
        uow,
        user,
        store,
        links,
        catalog,
        "1",
        None,
        SetupStep("reported", (9, 8), (" Bệnh khác ",)),
    )
    assert after.allergies == current.allergies
    assert after.conditions == SetupStep("reported", (8, 9), ("Bệnh khác",))
    links.insert.assert_called_once_with(uow, user, NewUserCondition(9))
    links.delete.assert_not_called()


def test_stale_or_unchanged_request_does_not_write():
    store, links = Mock(), Mock()
    links.list.return_value = []
    current = HealthSetup("2", SetupStep("none_known"), SetupStep("unreported"))
    store.read.return_value = current
    args = (Mock(), uuid4(), store, links, _catalog())
    with pytest.raises(Conflict, match="health_setup_revision_conflict"):
        save_setup(*args, "1", SetupStep("none_known"), None)
    assert save_setup(*args, "2", SetupStep("none_known"), None) is current
    store.save.assert_not_called()
    links.insert.assert_not_called()


def _allergy_save(stored, requested, active):
    uow, store, links, catalog = Mock(), Mock(), Mock(), _catalog()
    links.list.return_value = []
    store.read.return_value = HealthSetup(
        "1",
        SetupStep("reported", tuple(stored)) if stored else SetupStep("unreported"),
        SetupStep("unreported"),
    )
    store.save.return_value = "2"
    catalog.active_allergen_ids.side_effect = lambda _uow, ids: set(ids) & set(active)
    result = save_setup(
        uow, uuid4(), store, links, catalog, "1", SetupStep("reported", tuple(requested)), None
    )
    return result, store, catalog


def test_save_rejects_unknown_allergen():
    with pytest.raises(DomainError, match="allergen_not_found"):
        _allergy_save([], ["penicillin", "made_up"], active={"penicillin"})


def test_save_rejects_newly_added_inactive_allergen():
    with pytest.raises(DomainError, match="allergen_not_found"):
        _allergy_save(["penicillin"], ["penicillin", "retired_one"], active={"penicillin"})


def test_save_accepts_already_stored_inactive_allergen():
    result, store, catalog = _allergy_save(
        ["retired_one"], ["retired_one", "milk"], active={"milk"}
    )
    assert result.allergies == SetupStep("reported", ("milk", "retired_one"))
    # Only ids not already stored are looked up in the active catalog.
    assert catalog.active_allergen_ids.call_args.args[1] == ["milk"]
    store.save.assert_called_once()


def test_save_resubmitting_stored_ids_skips_catalog_lookup():
    _, store, catalog = _allergy_save(["retired_one"], ["retired_one"], active=set())
    catalog.active_allergen_ids.assert_not_called()
    store.save.assert_not_called()


def _setup(links_list, current):
    uow, store, links, catalog = Mock(), Mock(), Mock(), _catalog()
    links.list.return_value = links_list
    store.read.return_value = current
    store.save.return_value = "2"
    return uow, store, links, catalog


@pytest.mark.parametrize(
    ("conditions", "physiological"),
    [
        (SetupStep("reported", (30,)), None),  # pregnancy sent as a chronic disease
        (None, SetupStep("reported", (8,))),  # diabetes sent as a physiological state
    ],
)
def test_category_mismatch_rejected_before_write__AC25(conditions, physiological):
    current = HealthSetup("1", SetupStep("unreported"), SetupStep("unreported"))
    uow, store, links, catalog = _setup([], current)
    with pytest.raises(DomainError, match="condition_category_mismatch"):
        save_setup(uow, uuid4(), store, links, catalog, "1", None, conditions, physiological)
    store.save.assert_not_called()
    links.insert.assert_not_called()
    links.delete.assert_not_called()


def test_unknown_physiological_id_is_condition_not_found():
    current = HealthSetup("1", SetupStep("unreported"), SetupStep("unreported"))
    uow, store, links, catalog = _setup([], current)
    with pytest.raises(DomainError, match="condition_not_found"):
        save_setup(
            uow, uuid4(), store, links, catalog, "1", None, None, SetupStep("reported", (99,))
        )
    store.save.assert_not_called()


def test_physiological_none_known_clears_only_physiological_links__AC25():
    user = uuid4()
    chronic = UserConditionRecord(1, 8, None, None)
    pregnancy = UserConditionRecord(2, 30, None, None)
    current = HealthSetup(
        "1",
        SetupStep("none_known"),
        SetupStep("reported", (8,)),
        SetupStep("reported", (30,)),
    )
    uow, store, links, catalog = _setup([chronic, pregnancy], current)
    after = save_setup(uow, user, store, links, catalog, "1", None, None, SetupStep("none_known"))
    assert after.physiological_states == SetupStep("none_known")
    assert after.conditions == current.conditions
    links.delete.assert_called_once_with(uow, user, 2)
    links.insert.assert_not_called()
    assert store.save.call_args.args[4] == SetupStep("none_known")


def test_conditions_none_known_survives_physiological_change__AC17():
    user = uuid4()
    current = HealthSetup("1", SetupStep("none_known"), SetupStep("none_known"))
    uow, store, links, catalog = _setup([], current)
    after = save_setup(
        uow, user, store, links, catalog, "1", None, None, SetupStep("reported", (31,))
    )
    assert after.conditions == SetupStep("none_known")
    assert after.physiological_states == SetupStep("reported", (31,))
    links.insert.assert_called_once_with(uow, user, NewUserCondition(31))
    assert store.save.call_args.args[3] == SetupStep("none_known")


def test_chronic_step_does_not_touch_physiological_links():
    user = uuid4()
    pregnancy = UserConditionRecord(2, 30, None, None)
    current = HealthSetup(
        "1", SetupStep("none_known"), SetupStep("unreported"), SetupStep("reported", (30,))
    )
    uow, store, links, catalog = _setup([pregnancy], current)
    save_setup(uow, user, store, links, catalog, "1", None, SetupStep("none_known"))
    links.delete.assert_not_called()


def test_identical_three_step_save_is_idempotent__AC25():
    current = HealthSetup(
        "3",
        SetupStep("none_known"),
        SetupStep("reported", (8,)),
        SetupStep("reported", (30, 31)),
    )
    uow, store, links, catalog = _setup(
        [
            UserConditionRecord(1, 8, None, None),
            UserConditionRecord(2, 30, None, None),
            UserConditionRecord(3, 31, None, None),
        ],
        current,
    )
    result = save_setup(
        uow,
        uuid4(),
        store,
        links,
        catalog,
        "3",
        SetupStep("none_known"),
        SetupStep("reported", (8,)),
        SetupStep("reported", (31, 30)),
    )
    assert result is current
    store.save.assert_not_called()
    links.insert.assert_not_called()
    links.delete.assert_not_called()
