from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.medication.application.manage_health_setup import save_setup
from drugtime.modules.medication.domain.health_setup import (
    HealthSetup,
    SetupStep,
    normalize_custom_names,
)
from drugtime.modules.medication.domain.user_condition import NewUserCondition, UserConditionRecord
from drugtime.shared.errors import Conflict, DomainError


def test_custom_names_normalize_and_reject_duplicate_or_blank():
    assert normalize_custom_names(("  Ha\u0309i sản ",)) == ("Hải sản",)
    with pytest.raises(DomainError, match="duplicate_custom_name"):
        normalize_custom_names(("Tôm", " TÔM "))
    with pytest.raises(DomainError, match="invalid_custom_name"):
        normalize_custom_names(("  ",))


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
        lambda _: True,
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
    args = (Mock(), uuid4(), store, links, Mock(), lambda _: True)
    with pytest.raises(Conflict, match="health_setup_revision_conflict"):
        save_setup(*args, "1", SetupStep("none_known"), None)
    assert save_setup(*args, "2", SetupStep("none_known"), None) is current
    store.save.assert_not_called()
    links.insert.assert_not_called()
