"""Patient/filter-bound descending keyset cursor. Authorization precedes decoding."""

import base64
import binascii
import json
from uuid import UUID

from drugtime.shared.errors import DomainError


def encode(patient_id: UUID, last_id: int) -> str:
    raw = json.dumps([str(patient_id), "active", last_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode(cursor: str, patient_id: UUID) -> int:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (
            not isinstance(data, list)
            or len(data) != 3
            or data[0] != str(patient_id)
            or data[1] != "active"
            or type(data[2]) is not int
            or not 0 < data[2] <= 9223372036854775807
        ):
            raise ValueError("invalid cursor")
        return data[2]
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise DomainError("invalid_cursor") from exc
