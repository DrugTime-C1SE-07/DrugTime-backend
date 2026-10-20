import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from drugtime.shared.errors import DomainError

GENDERS = {"nam", "nu", "khac", "male", "female", "other"}
VIETNAM = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")

_EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def validate_email(email: str | None) -> str | None:
    if email is None:
        return None

    normalized_email = email.strip().lower()

    if (
        len(normalized_email) > 254
        or not _EMAIL_PATTERN.fullmatch(normalized_email)
    ):
        raise DomainError("invalid_email")

    return normalized_email


@dataclass(frozen=True)
class ProfileRecord:
    full_name: str | None
    date_of_birth: date | None
    gender: str | None
    email: str | None


def validate_profile(
    full_name: str,
    date_of_birth: date,
    gender: str,
    email: str | None = None,
    *,
    at: datetime,
) -> ProfileRecord:
    full_name = full_name.strip()
    if not full_name or "\x00" in full_name:
        raise DomainError("invalid_full_name")

    gender = gender.strip().lower()
    if gender not in GENDERS:
        raise DomainError("invalid_gender")

    normalized_email = validate_email(email)

    # Existing callers can pass naive test clocks; interpret those as UTC.
    instant = at if at.tzinfo else at.replace(tzinfo=UTC)
    if date_of_birth > instant.astimezone(VIETNAM).date():
        raise DomainError("invalid_date_of_birth")

    return ProfileRecord(
        full_name=full_name,
        date_of_birth=date_of_birth,
        gender=gender,
        email=normalized_email,
    )
