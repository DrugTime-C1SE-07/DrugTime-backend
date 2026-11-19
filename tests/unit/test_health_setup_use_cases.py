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
from drugtime.modules.medication.domain.user_condition import NewUserCondition, UserConditionRecord
from drugtime.shared.errors import Conflict, DomainError


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
    uow, store, links, catalog = Mock(), Mock(), Mock(), Mock()
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
    uow, store, links, catalog = Mock(), Mock(), Mock(), Mock()
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
    current = HealthSetup("2", SetupStep("none_known"), SetupStep("unreported"))
    store.read.return_value = current
    args = (Mock(), uuid4(), store, links, Mock())
    with pytest.raises(Conflict, match="health_setup_revision_conflict"):
        save_setup(*args, "1", SetupStep("none_known"), None)
    assert save_setup(*args, "2", SetupStep("none_known"), None) is current
    store.save.assert_not_called()
    links.insert.assert_not_called()


def _allergy_save(stored, requested, active):
    uow, store, links, catalog = Mock(), Mock(), Mock(), Mock()
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
