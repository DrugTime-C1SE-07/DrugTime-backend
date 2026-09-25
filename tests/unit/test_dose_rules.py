from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from drugtime.modules.adherence.domain.dose import (
    DoseConfirmation,
    DoseStatus,
    may_mark_missed,
    status_after_confirmation,
    validate_confirmation,
)
from drugtime.shared.errors import DomainError


def test_confirmation_transitions():
    assert status_after_confirmation(None) is DoseStatus.TAKEN
    assert status_after_confirmation(DoseStatus.MISSED) is DoseStatus.LATE
    assert status_after_confirmation(DoseStatus.TAKEN) is DoseStatus.TAKEN
    assert status_after_confirmation(DoseStatus.LATE) is DoseStatus.LATE


def test_worker_never_overwrites():
    assert may_mark_missed(None)
    assert not any(may_mark_missed(s) for s in DoseStatus)


def test_future_taken_at_rejected():
    now = datetime.now(UTC)
    c = DoseConfirmation(uuid4(), uuid4(), now, now + timedelta(minutes=5))
    with pytest.raises(DomainError):
        validate_confirmation(c, now)
