from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.identity.application.profile import get_profile, update_profile
from drugtime.modules.identity.domain.profile import ProfileRecord, validate_profile
from drugtime.shared.errors import Conflict, DomainError, ServiceUnavailable, Unauthorized


def test_vietnam_midnight_and_normalization():
    at = datetime(2026, 10, 12, 18, tzinfo=UTC)
    result = validate_profile("  Bao  ", date(2026, 10, 13), " MALE ", at=at)
    assert result.full_name == "Bao"
    assert result.gender == "male"
    with pytest.raises(DomainError, match="invalid_date_of_birth"):
        validate_profile("Bao", date(2026, 10, 14), "nam", at=at)


@pytest.mark.parametrize("gender", ["nam", "nu", "khac", "male", "female", "other"])
def test_all_genders(gender):
    assert (
        validate_profile("Bao", date(2000, 1, 1), gender, at=datetime(2026, 1, 1)).gender == gender
    )


@pytest.mark.parametrize("name,gender", [("", "nam"), ("   ", "nu"), ("Bao", "invalid")])
def test_invalid_fields(name, gender):
    with pytest.raises(DomainError):
        validate_profile(name, date(2000, 1, 1), gender, at=datetime(2026, 1, 1))


def test_missing_or_erased_profile_unauthorized():
    users = Mock()
    users.get_profile.return_value = None
    with pytest.raises(Unauthorized):
        get_profile(users, uuid4())


def test_email_is_trimmed_and_lowercased():
    result = validate_profile(
        "Bao", date(2000, 1, 1), "nam", "  Bao@Example.com ", at=datetime(2026, 1, 1)
    )
    assert result.email == "bao@example.com"


@pytest.mark.parametrize("email", ["", "not-an-email", "a@b", "x" * 250 + "@example.com"])
def test_invalid_email_is_rejected(email):
    with pytest.raises(DomainError, match="invalid_email"):
        validate_profile(
            "Bao", date(2000, 1, 1), "nam", email=email, at=datetime(2026, 1, 1)
        )


def test_profile_update_changes_auth_and_database_email_for_same_user():
    user_id = uuid4()
    users = Mock()
    users.get_profile.return_value = ProfileRecord(
        "Bao", date(2000, 1, 1), "nam", "old@example.com"
    )
    auth = Mock()

    result = update_profile(
        users,
        auth,
        user_id,
        full_name="Bao Nguyen",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        email=" New@example.com ",
        at=datetime(2026, 1, 1),
    )

    auth.update_email.assert_called_once_with(user_id, "new@example.com")
    users.update_profile.assert_called_once_with(
        user_id,
        full_name="Bao Nguyen",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        email="new@example.com",
    )
    assert result.previous_email == "old@example.com"
    assert result.auth_email_changed


def test_profile_update_without_email_preserves_existing_auth_and_db_email():
    user_id = uuid4()
    users = Mock()
    users.get_profile.return_value = ProfileRecord(
        "Bao", date(2000, 1, 1), "nam", "Current@Example.com"
    )
    auth = Mock()

    result = update_profile(
        users,
        auth,
        user_id,
        full_name="Bao Nguyen",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        at=datetime(2026, 1, 1),
    )

    auth.update_email.assert_not_called()
    users.update_profile.assert_called_once_with(
        user_id,
        full_name="Bao Nguyen",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        email="Current@Example.com",
    )
    assert not result.auth_email_changed


def test_profile_update_restores_auth_email_when_database_update_fails():
    user_id = uuid4()
    users = Mock()
    users.get_profile.return_value = ProfileRecord(
        "Bao", date(2000, 1, 1), "nam", "old@example.com"
    )
    users.update_profile.side_effect = Conflict("email_change_unavailable")
    auth = Mock()

    with pytest.raises(Conflict, match="email_change_unavailable"):
        update_profile(
            users,
            auth,
            user_id,
            full_name="Bao",
            date_of_birth=date(2000, 1, 1),
            gender="nam",
            email="new@example.com",
            at=datetime(2026, 1, 1),
        )

    assert auth.update_email.call_args_list == [
        ((user_id, "new@example.com"),),
        ((user_id, "old@example.com"),),
    ]


def test_profile_update_reports_failed_auth_compensation():
    user_id = uuid4()
    users = Mock()
    users.get_profile.return_value = ProfileRecord(
        "Bao", date(2000, 1, 1), "nam", "old@example.com"
    )
    users.update_profile.side_effect = Conflict("email_change_unavailable")
    auth = Mock()
    auth.update_email.side_effect = [None, ServiceUnavailable("auth_provider_unavailable")]

    with pytest.raises(ServiceUnavailable, match="auth_provider_unavailable"):
        update_profile(
            users,
            auth,
            user_id,
            full_name="Bao",
            date_of_birth=date(2000, 1, 1),
            gender="nam",
            email="new@example.com",
            at=datetime(2026, 1, 1),
        )


@pytest.mark.parametrize("name", ["\x00", "Bao\x00Test", "\x00Bao", "Bao\x00"])
def test_nul_name_rejected_before_storage(name):
    with pytest.raises(DomainError, match="invalid_full_name"):
        validate_profile(name, date(2000, 1, 1), "nam", at=datetime(2026, 1, 1))
