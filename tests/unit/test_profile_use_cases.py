from datetime import date, datetime
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from drugtime.modules.medication.application.manage_profile import get_profile, update_profile
from drugtime.modules.medication.application.manage_user_conditions import (
    create_condition,
    delete_condition,
    update_condition,
)
from drugtime.modules.medication.domain.user_condition import (
    NewUserCondition,
    PersonalProfile,
    UserConditionRecord,
)
from drugtime.shared.errors import Conflict, DomainError, Forbidden, NotFound

USER = uuid4()


@pytest.fixture
def deps():
    return dict(
        uow=object(), user_id=USER, is_admin=False, access=Mock(), conditions=Mock(), catalog=Mock()
    )


def test_profile_nullable_and_batched_names(deps):
    profiles = Mock()
    profiles.get.return_value = PersonalProfile(None, None, None)
    deps["conditions"].list.return_value = [
        UserConditionRecord(2, 3, None, "A"),
        UserConditionRecord(5, 7, "", None),
    ]
    deps["catalog"].names.return_value = {3: "Diabetes", 7: "Hypertension"}
    result = get_profile(**deps, profiles=profiles)
    assert result.full_name is None
    assert [link.id for link in result.conditions] == [2, 5]
    deps["catalog"].names.assert_called_once_with(deps["uow"], [3, 7])
    deps["access"].authorize_read.assert_called_once_with(deps["uow"], USER, False)


def test_put_only_updates_personal_profile(deps):
    profiles = Mock()
    deps.pop("conditions")
    deps.pop("catalog")
    update_profile(
        **deps,
        profiles=profiles,
        full_name="Bao",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        at=datetime(2026, 1, 1),
    )
    profiles.update.assert_called_once()
    deps["access"].authorize_write.assert_called_once()


def test_create_duplicate_and_missing_catalog(deps):
    deps["catalog"].get_name.return_value = None
    with pytest.raises(DomainError, match="condition_not_found"):
        create_condition(**deps, cmd=NewUserCondition(1))
    deps["conditions"].insert.assert_not_called()
    deps["catalog"].get_name.return_value = "Diabetes"
    deps["conditions"].insert.return_value = None
    with pytest.raises(Conflict, match="condition_already_exists"):
        create_condition(**deps, cmd=NewUserCondition(1))


def test_create_and_patch_preserve_metadata(deps):
    deps["catalog"].get_name.return_value = "Diabetes"
    record = UserConditionRecord(10, 1, None, "unchanged")
    deps["conditions"].insert.return_value = record
    assert create_condition(**deps, cmd=NewUserCondition(1)).id == 10
    deps["conditions"].update.return_value = record
    assert update_condition(**deps, link_id=10, fields={"subtype": None}).stage == "unchanged"
    deps["conditions"].update.assert_called_once_with(deps["uow"], USER, 10, {"subtype": None})


@pytest.mark.parametrize("fields", [{}, {"condition_id": 8}, {"user_id": str(USER)}])
def test_invalid_patch_does_not_write(deps, fields):
    with pytest.raises(DomainError):
        update_condition(**deps, link_id=1, fields=fields)
    deps["conditions"].update.assert_not_called()


def test_unknown_or_other_owner_same_not_found(deps):
    deps["conditions"].update.return_value = None
    with pytest.raises(NotFound, match="user_condition_not_found"):
        update_condition(**deps, link_id=99, fields={"stage": None})
    deps["catalog"].get_name.assert_not_called()
    deps.pop("catalog")
    deps["conditions"].delete.return_value = False
    with pytest.raises(NotFound, match="user_condition_not_found"):
        delete_condition(**deps, link_id=99)


@pytest.mark.parametrize("operation", ["get", "put", "create", "patch", "delete"])
def test_denial_precedes_business_ports(deps, operation):
    profiles = Mock()
    deps["access"].authorize_read.side_effect = Forbidden("consent_revoked")
    deps["access"].authorize_write.side_effect = Forbidden("consent_revoked")
    with pytest.raises(Forbidden):
        if operation == "get":
            get_profile(**deps, profiles=profiles)
        elif operation == "put":
            update_profile(
                **{k: v for k, v in deps.items() if k not in {"catalog", "conditions"}},
                profiles=profiles,
                full_name="Bao",
                date_of_birth=date(2000, 1, 1),
                gender="nam",
                at=datetime(2026, 1, 1),
            )
        elif operation == "create":
            create_condition(**deps, cmd=NewUserCondition(1))
        elif operation == "patch":
            update_condition(**deps, link_id=1, fields={"stage": None})
        else:
            delete_condition(**{k: v for k, v in deps.items() if k != "catalog"}, link_id=1)
    assert profiles.mock_calls == []
    assert deps["conditions"].mock_calls == []
    assert deps["catalog"].mock_calls == []


def test_sql_owner_scoped_and_hard_delete():
    from drugtime.modules.medication.adapters.outbound.sql_user_conditions import SqlUserConditions

    uow = Mock()
    uow.connection.execute.return_value.first.return_value = None
    sql = SqlUserConditions()
    assert not sql.delete(uow, USER, 9)
    statement, params = uow.connection.execute.call_args.args
    assert "DELETE FROM user_conditions" in str(statement)
    assert "user_id = :user_id" in str(statement)
    assert params == {"link_id": 9, "user_id": USER}
    assert sql.update(uow, USER, 9, {"stage": None}) is None
    statement, params = uow.connection.execute.call_args.args
    assert "subtype =" not in str(statement)
    assert params["stage"] is None


def test_sql_insert_conflict_and_fk_savepoint():
    from sqlalchemy.exc import IntegrityError

    from drugtime.modules.medication.adapters.outbound.sql_user_conditions import SqlUserConditions

    uow = MagicMock()
    uow.connection.execute.return_value.first.return_value = None
    sql = SqlUserConditions()
    assert sql.insert(uow, USER, NewUserCondition(1)) is None
    statement, _ = uow.connection.execute.call_args.args
    assert "ON CONFLICT (user_id, condition_id) DO NOTHING" in str(statement)
    orig = Mock(sqlstate="23503")
    orig.diag.constraint_name = "user_conditions_condition_id_fkey"
    uow.connection.execute.side_effect = IntegrityError("sql", {}, orig)
    with pytest.raises(DomainError, match="condition_not_found"):
        sql.insert(uow, USER, NewUserCondition(1))
    orig.diag.constraint_name = "unrelated_constraint"
    with pytest.raises(IntegrityError):
        sql.insert(uow, USER, NewUserCondition(1))


@pytest.mark.parametrize("action", ["read", "write"])
def test_health_profile_adapter_scope_and_self_owner(monkeypatch, action):
    from drugtime.modules.access import api as access
    from drugtime.modules.medication.adapters.outbound.other_modules import (
        HealthProfileAccessAdapter,
    )

    authorize = Mock()
    monkeypatch.setattr(access, "authorize", authorize)
    uow = object()
    getattr(HealthProfileAccessAdapter(), "authorize_" + action)(uow, USER, False)
    authorize.assert_called_once_with(
        uow,
        caller_id=USER,
        caller_is_admin=False,
        patient_id=USER,
        scope=access.Scope.HEALTH_PROFILE,
        action=access.Action(action),
    )
