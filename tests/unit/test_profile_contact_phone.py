from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from drugtime.modules.identity.adapters.outbound.sql_users import SqlUsers
from drugtime.modules.identity.application.profile import update_profile
from drugtime.modules.identity.domain.profile import ProfileRecord, normalize_contact_phone
from drugtime.modules.medication.adapters.inbound import profile_schemas
from drugtime.modules.medication.domain.user_condition import HealthProfile
from drugtime.shared.errors import Conflict, DomainError


@pytest.mark.parametrize("value", ["0912345678", " 0912 345-678 ", "+84912345678"])
def test_contact_phone_normalization(value):
    assert normalize_contact_phone(value) == "+84912345678"


@pytest.mark.parametrize(
    "value",
    ["", " ", "123", "+012345678", "+1234567", "+1234567890123456", "+84abc12345", "+84١٢٣٤٥٦٧٨٩"],
)
def test_invalid_contact_phone(value):
    with pytest.raises(DomainError, match="invalid_phone"):
        normalize_contact_phone(value)


def test_contact_phone_update_does_not_change_auth_or_email():
    users, auth, uid = Mock(), Mock(), uuid4()
    users.get_profile.return_value = ProfileRecord("Bao", None, None, "bao@example.com")
    result = update_profile(
        users,
        auth,
        uid,
        full_name="Bao",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        phone_number="0912345678",
        at=datetime(2026, 1, 1),
    )
    assert auth.mock_calls == []
    assert not result.auth_email_changed
    assert users.update_profile.call_args.kwargs["phone_number"] == "+84912345678"
    assert "email" not in users.update_profile.call_args.kwargs


def test_invalid_phone_rejected_before_auth_or_database_update():
    users, auth = Mock(), Mock()
    users.get_profile.return_value = ProfileRecord("Bao", None, None, "bao@example.com")
    with pytest.raises(DomainError, match="invalid_phone"):
        update_profile(
            users,
            auth,
            uuid4(),
            full_name="Bao",
            date_of_birth=date(2000, 1, 1),
            gender="nam",
            phone_number="bad",
            email="new@example.com",
            at=datetime(2026, 1, 1),
        )
    assert auth.mock_calls == []
    users.update_profile.assert_not_called()


def test_omitted_phone_is_not_written():
    uow = Mock()
    uow.connection.execute.return_value.rowcount = 1
    SqlUsers(uow).update_profile(uuid4(), full_name="Bao", date_of_birth=None, gender="nam")
    statement, params = uow.connection.execute.call_args.args
    assert "phone_number" not in str(statement)
    assert "phone_number" not in params


def test_phone_write_is_owner_scoped_and_parameterized():
    uow, uid = Mock(), uuid4()
    uow.connection.execute.return_value.rowcount = 1
    SqlUsers(uow).update_profile(
        uid,
        full_name="Bao",
        date_of_birth=None,
        gender="nam",
        phone_number="+84912345678",
    )
    statement, params = uow.connection.execute.call_args.args
    assert "phone_number = :phone_number" in str(statement)
    assert "WHERE id = :id AND erased_at IS NULL" in str(statement)
    assert params["id"] == uid
    assert params["phone_number"] == "+84912345678"


def test_duplicate_phone_returns_generic_conflict():
    uow = Mock()
    original = SimpleNamespace(diag=SimpleNamespace(constraint_name="users_phone_number_key"))
    uow.connection.execute.side_effect = IntegrityError("private SQL", {}, original)
    with pytest.raises(Conflict, match="phone_change_unavailable"):
        SqlUsers(uow).update_profile(
            uuid4(),
            full_name="Bao",
            date_of_birth=None,
            gender="nam",
            phone_number="+84912345678",
        )


@pytest.mark.parametrize("value", [None, "", 912345678, True])
def test_explicit_invalid_phone_shape_rejected(value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        profile_schemas.ProfileUpdateRequest.model_validate(
            {
                "full_name": "Bao",
                "date_of_birth": "2000-01-01",
                "gender": "nam",
                "phone_number": value,
            }
        )


def test_profile_response_includes_contact_phone():
    profile = HealthProfile("Bao", None, None, "bao@example.com", [], "+84912345678")
    response = profile_schemas.HealthProfileResponse.model_validate(profile)
    assert response.phone_number == "+84912345678"


@pytest.mark.parametrize("digits,valid", [(7, False), (8, True), (15, True), (16, False)])
def test_normalized_phone_digit_boundaries(digits, valid):
    phone = "+" + "1" * digits
    if valid:
        assert normalize_contact_phone(phone) == phone
    else:
        with pytest.raises(DomainError, match="invalid_phone"):
            normalize_contact_phone(phone)


@pytest.mark.parametrize("size,valid", [(0, False), (1, True), (64, True), (65, False)])
def test_raw_phone_schema_length_boundaries(size, valid):
    from pydantic import ValidationError

    body = {
        "full_name": "Bao",
        "date_of_birth": "2000-01-01",
        "gender": "nam",
        "phone_number": "1" * size,
    }
    if valid:
        assert profile_schemas.ProfileUpdateRequest.model_validate(body).phone_number == "1" * size
    else:
        with pytest.raises(ValidationError):
            profile_schemas.ProfileUpdateRequest.model_validate(body)


@pytest.mark.parametrize(
    "value", ["\x00", "+84912345678\x00", "---", "\t\n", "+84 １２３４５６７８９"]
)
def test_contact_phone_control_and_non_ascii_rejected(value):
    with pytest.raises(DomainError, match="invalid_phone"):
        normalize_contact_phone(value)


def test_omitted_phone_application_does_not_overwrite_existing_phone():
    users, auth = Mock(), Mock()
    users.get_profile.return_value = ProfileRecord(
        "Bao", None, None, "bao@example.com", "+84912345678"
    )
    update_profile(
        users,
        auth,
        uuid4(),
        full_name="Bao",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        at=datetime(2026, 1, 1),
    )
    assert "phone_number" not in users.update_profile.call_args.kwargs
    assert auth.mock_calls == []


def test_sql_profile_reads_contact_phone_only_for_current_active_owner():
    uow, uid = Mock(), uuid4()
    uow.connection.execute.return_value.first.return_value = (
        "Bao",
        None,
        "nam",
        "bao@example.com",
        "+84912345678",
    )
    profile = SqlUsers(uow).get_profile(uid)
    assert profile.phone_number == "+84912345678"
    statement, params = uow.connection.execute.call_args.args
    assert "phone_number" in str(statement)
    assert "WHERE id = :id AND erased_at IS NULL" in str(statement)
    assert params == {"id": uid}


def test_unrelated_integrity_error_is_not_misreported_as_phone_conflict():
    uow = Mock()
    original = SimpleNamespace(diag=SimpleNamespace(constraint_name="some_other_constraint"))
    error = IntegrityError("private SQL", {}, original)
    uow.connection.execute.side_effect = error
    with pytest.raises(IntegrityError) as exc:
        SqlUsers(uow).update_profile(
            uuid4(), full_name="Bao", date_of_birth=None, gender="nam", phone_number="+84912345678"
        )
    assert exc.value is error


def test_simultaneous_email_change_rejects_phone_update_without_mutation():
    users, auth, uid = Mock(), Mock(), uuid4()
    users.get_profile.return_value = ProfileRecord("Bao", None, None, "old@example.com")
    users.update_profile.side_effect = Conflict("phone_change_unavailable")
    with pytest.raises(Conflict, match="email_change_verification_required"):
        update_profile(
            users,
            auth,
            uid,
            full_name="Bao",
            date_of_birth=date(2000, 1, 1),
            gender="nam",
            email="new@example.com",
            phone_number="0912345678",
            at=datetime(2026, 1, 1),
        )
    auth.update_email.assert_not_called()
    users.update_profile.assert_not_called()


def test_phone_propagates_through_identity_adapter_and_medication_read(monkeypatch):
    from drugtime.modules.identity import api as identity
    from drugtime.modules.medication.adapters.outbound.other_modules import IdentityProfileAdapter
    from drugtime.modules.medication.application.manage_profile import get_profile

    record = ProfileRecord("Bao", None, "nam", "bao@example.com", "+84912345678")
    monkeypatch.setattr(identity, "get_profile", lambda *a: record)
    conditions, catalog, access = Mock(), Mock(), Mock()
    conditions.list.return_value = []
    catalog.names.return_value = {}
    result = get_profile(
        object(),
        user_id=uuid4(),
        is_admin=False,
        access=access,
        profiles=IdentityProfileAdapter(),
        conditions=conditions,
        catalog=catalog,
    )
    assert result.phone_number == record.phone_number
    access.authorize_read.assert_called_once()


def test_identity_adapter_and_medication_write_forward_phone(monkeypatch):
    from drugtime.modules.identity import api as identity
    from drugtime.modules.identity.application.profile import ProfileUpdateResult
    from drugtime.modules.medication.adapters.outbound.other_modules import IdentityProfileAdapter
    from drugtime.modules.medication.application.manage_profile import update_profile as write

    update = Mock(return_value=ProfileUpdateResult("bao@example.com", False))
    monkeypatch.setattr(identity, "update_profile", update)
    access = Mock()
    write(
        object(),
        user_id=uuid4(),
        is_admin=False,
        access=access,
        profiles=IdentityProfileAdapter(),
        full_name="Bao",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        phone_number="0912345678",
        at=datetime(2026, 1, 1),
    )
    assert update.call_args.kwargs["phone_number"] == "0912345678"
    assert update.call_args.kwargs["email"] is None
    access.authorize_write.assert_called_once()
