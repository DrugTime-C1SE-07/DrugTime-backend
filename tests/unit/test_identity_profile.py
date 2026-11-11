from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.identity.application.profile import get_profile, update_profile
from drugtime.modules.identity.domain.profile import ProfileRecord, validate_profile
from drugtime.shared.errors import Conflict, DomainError, Unauthorized


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
        validate_profile("Bao", date(2000, 1, 1), "nam", email=email, at=datetime(2026, 1, 1))


def test_profile_update_rejects_direct_email_change_for_same_user():
    user_id = uuid4()
    users = Mock()
    users.get_profile.return_value = ProfileRecord(
        "Bao", date(2000, 1, 1), "nam", "old@example.com"
    )
    auth = Mock()

    with pytest.raises(Conflict, match="email_change_verification_required"):
        update_profile(
            users,
            auth,
            user_id,
            full_name="Bao Nguyen",
            date_of_birth=date(2000, 1, 1),
            gender="nam",
            email=" New@example.com ",
            at=datetime(2026, 1, 1),
        )
    auth.update_email.assert_not_called()
    users.update_profile.assert_not_called()


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
    )
    assert not result.auth_email_changed


def test_profile_update_with_same_email_does_not_change_auth():
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
        full_name="Bao",
        date_of_birth=date(2000, 1, 1),
        gender="nam",
        email=" OLD@example.com ",
        at=datetime(2026, 1, 1),
    )
    assert not result.auth_email_changed
    auth.update_email.assert_not_called()
    users.update_profile.assert_called_once_with(
        user_id, full_name="Bao", date_of_birth=date(2000, 1, 1), gender="nam"
    )


def test_profile_update_failure_does_not_modify_auth():
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
            email="old@example.com",
            at=datetime(2026, 1, 1),
        )
    auth.update_email.assert_not_called()


@pytest.mark.parametrize("name", ["\x00", "Bao\x00Test", "\x00Bao", "Bao\x00"])
def test_nul_name_rejected_before_storage(name):
    with pytest.raises(DomainError, match="invalid_full_name"):
        validate_profile(name, date(2000, 1, 1), "nam", at=datetime(2026, 1, 1))
