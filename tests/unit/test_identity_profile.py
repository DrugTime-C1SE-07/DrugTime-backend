from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.identity.application.profile import get_profile
from drugtime.modules.identity.domain.profile import validate_profile
from drugtime.shared.errors import DomainError, Unauthorized


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


@pytest.mark.parametrize("name", ["\x00", "Bao\x00Test", "\x00Bao", "Bao\x00"])
def test_nul_name_rejected_before_storage(name):
    with pytest.raises(DomainError, match="invalid_full_name"):
        validate_profile(name, date(2000, 1, 1), "nam", at=datetime(2026, 1, 1))
