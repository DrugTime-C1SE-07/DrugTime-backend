from datetime import UTC, datetime
from uuid import uuid4

import pytest

from drugtime.modules.consent.application.manage_consents import (
    grant_consent,
    list_consents,
    withdraw_consent,
)
from drugtime.modules.consent.domain.consent import (
    DOCUMENT_OUTDATED,
    NOT_WITHDRAWABLE,
    ActiveConsent,
)
from drugtime.modules.consent.domain.purpose import Purpose
from drugtime.shared.errors import DomainError

USER = uuid4()
UOW = object()
EARLIER = ActiveConsent(datetime(2026, 10, 1, 1, 0, tzinfo=UTC), "2026-10-v1")
NOW = ActiveConsent(datetime(2026, 10, 3, 10, 0, tzinfo=UTC), "2026-10-v1")
OUTDATED = ActiveConsent(datetime(2026, 9, 1, 1, 0, tzinfo=UTC), "2026-09-v0")


class FakeStore:
    """Giữ consent hiệu lực trong bộ nhớ; ghi lại mọi lời gọi ghi."""

    def __init__(self, active=None, conflict_with=None, replace_conflict_with=None):
        self.rows = dict(active or {})
        self.conflict_with = conflict_with  # mô phỏng request song song đã commit trước
        self.replace_conflict_with = replace_conflict_with  # song song đã thay phiên bản trước
        self.writes = []

    def active(self, uow, user_id):
        assert (uow, user_id) == (UOW, USER)
        return dict(self.rows)

    def insert_active(self, uow, user_id, purpose, document_version):
        self.writes.append(("insert", purpose, document_version))
        if self.conflict_with is not None:
            self.rows[purpose] = self.conflict_with
            return None
        if purpose in self.rows:
            return None
        self.rows[purpose] = NOW
        return NOW

    def replace_active(self, uow, user_id, purpose, document_version):
        self.writes.append(("replace", purpose, document_version))
        if self.replace_conflict_with is not None:
            self.rows[purpose] = self.replace_conflict_with
            return None
        self.rows[purpose] = NOW
        return NOW

    def withdraw_active(self, uow, user_id, purpose):
        self.writes.append(("withdraw", purpose))
        self.rows.pop(purpose, None)


def test_list_returns_four_states():
    states = list_consents(UOW, user_id=USER, store=FakeStore({Purpose.AI_MEAL: EARLIER}))
    assert [(s.purpose, s.active) for s in states] == [
        (Purpose.HEALTH_DATA, None),
        (Purpose.FAMILY_SHARING, None),
        (Purpose.AI_MEAL, EARLIER),
        (Purpose.TERMS, None),
    ]


def test_grant_creates_when_none_active():
    store = FakeStore()
    state, created = grant_consent(
        UOW, user_id=USER, purpose=Purpose.HEALTH_DATA, document_version="2026-10-v1", store=store
    )
    assert created is True
    assert (state.purpose, state.active) == (Purpose.HEALTH_DATA, NOW)
    assert store.writes == [("insert", Purpose.HEALTH_DATA, "2026-10-v1")]


def test_grant_returns_existing_without_new_row_when_active():
    store = FakeStore({Purpose.HEALTH_DATA: EARLIER})
    state, created = grant_consent(
        UOW, user_id=USER, purpose=Purpose.HEALTH_DATA, document_version="2026-10-v1", store=store
    )
    assert created is False
    assert state.active == EARLIER  # granted_at của lần trước giữ nguyên
    assert store.rows == {Purpose.HEALTH_DATA: EARLIER}


def test_grant_insert_conflict_rereads_existing():
    store = FakeStore(conflict_with=EARLIER)
    state, created = grant_consent(
        UOW,
        user_id=USER,
        purpose=Purpose.FAMILY_SHARING,
        document_version="2026-10-v1",
        store=store,
    )
    assert (created, state.active) == (False, EARLIER)


def test_grant_outdated_version_does_not_touch_store():
    store = FakeStore()
    with pytest.raises(DomainError) as exc:
        grant_consent(
            UOW,
            user_id=USER,
            purpose=Purpose.HEALTH_DATA,
            document_version="2026-09-v0",
            store=store,
        )
    assert str(exc.value) == DOCUMENT_OUTDATED
    assert store.writes == []


def test_withdraw_active_marks_not_granted_and_keeps_others():
    store = FakeStore({Purpose.HEALTH_DATA: EARLIER, Purpose.FAMILY_SHARING: EARLIER})
    state = withdraw_consent(UOW, user_id=USER, purpose=Purpose.FAMILY_SHARING, store=store)
    assert (state.purpose, state.active) == (Purpose.FAMILY_SHARING, None)
    assert store.rows == {Purpose.HEALTH_DATA: EARLIER}


def test_withdraw_without_active_is_noop_and_not_granted():
    store = FakeStore()
    state = withdraw_consent(UOW, user_id=USER, purpose=Purpose.AI_MEAL, store=store)
    assert state.active is None
    assert store.rows == {}


def _grant_terms(store):
    return grant_consent(
        UOW, user_id=USER, purpose=Purpose.TERMS, document_version="2026-10-v1", store=store
    )


def test_grant_terms_creates_when_none_active():
    store = FakeStore()
    state, created = _grant_terms(store)
    assert (created, state.purpose, state.active) == (True, Purpose.TERMS, NOW)
    assert store.writes == [("insert", Purpose.TERMS, "2026-10-v1")]


def test_grant_terms_outdated_replaces():
    store = FakeStore({Purpose.TERMS: OUTDATED})
    state, created = _grant_terms(store)
    assert (created, state.active) == (True, NOW)
    assert store.writes == [("replace", Purpose.TERMS, "2026-10-v1")]


def test_grant_terms_replace_race_returns_existing():
    store = FakeStore({Purpose.TERMS: OUTDATED}, replace_conflict_with=EARLIER)
    state, created = _grant_terms(store)
    assert (created, state.active) == (False, EARLIER)


def test_grant_terms_same_version_keeps():
    store = FakeStore({Purpose.TERMS: EARLIER})
    state, created = _grant_terms(store)
    assert (created, state.active) == (False, EARLIER)
    assert store.writes == []


def test_grant_health_data_outdated_keeps_old_row():
    # Chỉ terms được thay phiên bản; các mục đích khác giữ hành vi 1.14.
    store = FakeStore({Purpose.HEALTH_DATA: OUTDATED})
    state, created = grant_consent(
        UOW, user_id=USER, purpose=Purpose.HEALTH_DATA, document_version="2026-10-v1", store=store
    )
    assert (created, state.active) == (False, OUTDATED)
    assert store.writes == []


def test_grant_terms_outdated_request_version_does_not_touch_store():
    store = FakeStore({Purpose.TERMS: OUTDATED})
    with pytest.raises(DomainError) as exc:
        grant_consent(
            UOW, user_id=USER, purpose=Purpose.TERMS, document_version="2026-09-v0", store=store
        )
    assert str(exc.value) == DOCUMENT_OUTDATED
    assert store.writes == []


def test_withdraw_terms_raises_and_writes_nothing():
    store = FakeStore({Purpose.TERMS: EARLIER})
    with pytest.raises(DomainError) as exc:
        withdraw_consent(UOW, user_id=USER, purpose=Purpose.TERMS, store=store)
    assert str(exc.value) == NOT_WITHDRAWABLE
    assert store.writes == []
    assert store.rows == {Purpose.TERMS: EARLIER}
