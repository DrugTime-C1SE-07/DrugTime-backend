"""Use case gửi yêu cầu liên kết (task 3.13): mọi nhánh và thứ tự kiểm theo api_contract."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from drugtime.modules.family.application.send_link_request import (
    LinkRequestCommand,
    send_link_request,
)
from drugtime.modules.family.domain.link import FamilyLink, FamilyLinkError, LinkStatus
from drugtime.modules.family.domain.link_request import LinkRequestLimits
from drugtime.modules.family.domain.throttle import ThrottleState
from drugtime.shared.errors import Conflict, Forbidden, NotFound, TooManyRequests

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 10:00 giờ VN
CODE = "K7M2Q9XAR4"
LIMITS = LinkRequestLimits()


class World:
    """Fake chung cho mọi port; ghi thứ tự gọi để kiểm thứ tự kiểm."""

    def __init__(self, *, owner=None, consent=True):
        self.calls = []
        self.owner = owner
        self.consent = consent
        self.by_client_uuid = {}
        self.open_link = None
        self.created_today = 0
        self.streak = (0, None)
        self.state_value = ThrottleState()
        self.failures = []
        self.created = []

    # Links
    def lock_sender(self, uow, family_id):
        self.calls.append("lock_sender")

    def find_by_client_uuid(self, uow, family_id, client_uuid):
        self.calls.append("find_by_client_uuid")
        return self.by_client_uuid.get((family_id, client_uuid))

    def find_open_by_pair(self, uow, patient_id, family_id):
        self.calls.append("find_open_by_pair")
        return self.open_link

    def count_created_since(self, uow, family_id, since):
        self.calls.append("count_created_since")
        self.count_since = since
        return self.created_today

    def rejection_streak(self, uow, patient_id, family_id):
        self.calls.append("rejection_streak")
        return self.streak

    def create(self, uow, link):
        self.calls.append("create")
        saved = replace(link, id=15, linked_at=NOW)
        self.created.append(saved)
        return saved

    # LinkCodes
    def find_owner(self, uow, code):
        self.calls.append("find_owner")
        self.looked_up = code
        return self.owner

    # LinkAttempts
    def state(self, uow, family_id, client_uuid, now, limits):
        self.calls.append("state")
        return self.state_value

    def record_failure(self, family_id, client_uuid, attempted_at, locked_until):
        self.calls.append("record_failure")
        self.failures.append((family_id, client_uuid, attempted_at, locked_until))

    # Consents
    def has_family_sharing(self, uow, user_id):
        self.calls.append("has_family_sharing")
        self.consent_user = user_id
        return self.consent


def _send(world, caller, *, key=None, code=CODE, is_admin=False, now=NOW):
    return send_link_request(
        object(),
        caller_id=caller,
        caller_is_admin=is_admin,
        cmd=LinkRequestCommand(client_uuid=key or uuid4(), code=code),
        now=now,
        links=world,
        codes=world,
        attempts=world,
        consents=world,
        limits=LIMITS,
    )


def test_creates_pending__AC1():
    patient, family, key = uuid4(), uuid4(), uuid4()
    world = World(owner=patient)

    link, created = _send(world, family, key=key)

    assert created is True
    assert (link.patient_user_id, link.family_user_id) == (patient, family)
    assert link.status is LinkStatus.PENDING
    assert link.sharing_enabled is False
    assert link.client_uuid == key
    assert world.failures == []
    assert world.consent_user == patient  # consent của chủ mã, không phải người gọi (AC34)


def test_admin_forbidden_before_queries__AC16():
    world = World(owner=uuid4())

    with pytest.raises(Forbidden) as exc:
        _send(world, uuid4(), is_admin=True)

    assert str(exc.value) == "khong_co_quyen"
    assert world.calls == []


def test_lock_sender_called_before_replay__AC13():
    world = World(owner=uuid4())

    _send(world, uuid4())

    assert world.calls[:3] == ["lock_sender", "find_by_client_uuid", "state"]


def test_full_check_order_on_success():
    world = World(owner=uuid4())

    _send(world, uuid4())

    assert world.calls == [
        "lock_sender",
        "find_by_client_uuid",
        "state",
        "count_created_since",
        "find_owner",
        "has_family_sharing",
        "find_open_by_pair",
        "rejection_streak",
        "create",
    ]


def test_replay_returns_existing_not_created__AC29():
    family, key = uuid4(), uuid4()
    earlier = FamilyLink(15, uuid4(), family, LinkStatus.ACTIVE, linked_at=NOW, client_uuid=key)
    world = World(owner=uuid4())
    world.by_client_uuid[(family, key)] = earlier

    link, created = _send(world, family, key=key)

    assert (link, created) == (earlier, False)
    assert world.calls == ["lock_sender", "find_by_client_uuid"]


def test_replay_ignores_new_code__AC30():
    family, key = uuid4(), uuid4()
    earlier = FamilyLink(15, uuid4(), family, LinkStatus.PENDING, client_uuid=key)
    world = World(owner=None)  # mã mới không tồn tại, nhưng body lần sau bị bỏ qua
    world.by_client_uuid[(family, key)] = earlier

    link, created = _send(world, family, key=key, code="ZZZZZZZZZZ")

    assert (link.id, created) == (15, False)
    assert "find_owner" not in world.calls and world.failures == []


def test_replay_isolated_per_user__AC30():
    key = uuid4()
    world = World(owner=uuid4())
    world.by_client_uuid[(uuid4(), key)] = FamilyLink(15, uuid4(), uuid4(), LinkStatus.PENDING)

    _, created = _send(world, uuid4(), key=key)

    assert created is True


def test_replay_allowed_while_locked__AC29():
    family, key = uuid4(), uuid4()
    world = World(owner=uuid4())
    world.by_client_uuid[(family, key)] = FamilyLink(15, uuid4(), family, LinkStatus.PENDING)
    world.state_value = ThrottleState(locked_until=NOW + timedelta(minutes=5))
    world.created_today = 10

    _, created = _send(world, family, key=key)

    assert created is False


def test_locked_raises_429_with_retry_after__AC10():
    world = World(owner=uuid4())  # mã đúng vẫn bị chặn trong lúc khóa
    world.state_value = ThrottleState(
        failures_in_window=5, locked_until=NOW + timedelta(seconds=540)
    )

    with pytest.raises(TooManyRequests) as exc:
        _send(world, uuid4())

    assert (str(exc.value), exc.value.retry_after) == ("link_request_locked", 540)
    assert "find_owner" not in world.calls and world.created == [] and world.failures == []


def test_expired_lock_does_not_block__AC10():
    world = World(owner=uuid4())
    world.state_value = ThrottleState(locked_until=NOW)

    _, created = _send(world, uuid4())

    assert created is True


def test_daily_limit_before_lookup__AC14():
    world = World(owner=None)  # mã sai: không được tính lần sai khi đã đủ 10 yêu cầu
    world.created_today = 10

    with pytest.raises(TooManyRequests) as exc:
        _send(world, uuid4())

    # 10:00 giờ VN → còn 14 giờ tới 00:00 hôm sau.
    assert (str(exc.value), exc.value.retry_after) == ("link_request_daily_limit", 14 * 3600)
    assert world.count_since == datetime(2026, 10, 15, 17, tzinfo=UTC)
    assert "find_owner" not in world.calls and world.failures == []


def test_ninth_and_tenth_request_allowed__AC14():
    world = World(owner=uuid4())
    world.created_today = 9

    _, created = _send(world, uuid4())

    assert created is True


def test_unknown_code_records_failure_and_404__AC4():
    family, key = uuid4(), uuid4()
    world = World(owner=None)
    world.state_value = ThrottleState(failures_in_window=1)

    with pytest.raises(NotFound) as exc:
        _send(world, family, key=key)

    assert str(exc.value) == "link_code_not_found"
    assert world.failures == [(family, key, NOW, None)]
    assert world.created == []


def test_fifth_failure_records_lock__AC10():
    world = World(owner=None)
    world.state_value = ThrottleState(failures_in_window=4)

    with pytest.raises(NotFound):
        _send(world, uuid4())

    assert world.failures[0][3] == NOW + timedelta(minutes=15)


def test_replayed_failure_not_double_counted__AC31():
    world = World(owner=None)
    world.state_value = ThrottleState(failures_in_window=4, client_uuid_failed=True)

    with pytest.raises(NotFound):
        _send(world, uuid4())

    assert world.failures == []


def test_self_code_422_not_counted__AC5():
    caller = uuid4()
    world = World(owner=caller)

    with pytest.raises(FamilyLinkError) as exc:
        _send(world, caller)

    assert str(exc.value) == "self_link_not_allowed"
    assert world.failures == [] and world.created == []
    assert "has_family_sharing" not in world.calls


def test_owner_without_consent_same_as_unknown__AC33():
    family, key = uuid4(), uuid4()
    unknown, no_consent = World(owner=None), World(owner=uuid4(), consent=False)

    with pytest.raises(NotFound) as unknown_exc:
        _send(unknown, family, key=key)
    with pytest.raises(NotFound) as consent_exc:
        _send(no_consent, family, key=key)

    assert type(unknown_exc.value) is type(consent_exc.value)
    assert str(unknown_exc.value) == str(consent_exc.value) == "link_code_not_found"
    assert no_consent.failures == [(family, key, NOW, None)]
    assert no_consent.created == []


def test_pending_pair_409_not_counted__AC6():
    patient, family = uuid4(), uuid4()
    world = World(owner=patient)
    world.open_link = FamilyLink(3, patient, family, LinkStatus.PENDING)

    with pytest.raises(Conflict) as exc:
        _send(world, family)

    assert str(exc.value) == "link_request_pending"
    assert world.failures == [] and world.created == []


def test_active_pair_409__AC6():
    patient, family = uuid4(), uuid4()
    world = World(owner=patient)
    world.open_link = FamilyLink(3, patient, family, LinkStatus.ACTIVE, sharing_enabled=False)

    with pytest.raises(Conflict) as exc:
        _send(world, family)

    assert str(exc.value) == "already_linked"


def test_reverse_direction_allowed__AC7():
    # Chiều ngược (F là người bệnh của P) không phải "cặp" của yêu cầu này: adapter tra theo
    # (chủ mã, người gọi), nên không có dòng mở nào trả về.
    patient, family = uuid4(), uuid4()
    world = World(owner=patient)

    link, created = _send(world, family)

    assert created and (link.patient_user_id, link.family_user_id) == (patient, family)


def test_rejected_1_to_4_times_can_resend__AC8():
    world = World(owner=uuid4())
    world.streak = (4, NOW - timedelta(minutes=1))

    _, created = _send(world, uuid4())

    assert created is True


def test_cooldown_429__AC8b():
    world = World(owner=uuid4())
    fifth = NOW - timedelta(hours=23, minutes=59)
    world.streak = (5, fifth)

    with pytest.raises(TooManyRequests) as exc:
        _send(world, uuid4())

    assert (str(exc.value), exc.value.retry_after) == ("link_request_cooldown", 60)
    assert world.failures == [] and world.created == []


def test_cooldown_over_after_24h__AC8b():
    world = World(owner=uuid4())
    world.streak = (5, NOW - timedelta(hours=24))

    _, created = _send(world, uuid4())

    assert created is True


def test_reopen_after_revoked_sharing_false__AC9():
    world = World(owner=uuid4())  # dòng revoked cũ không phải dòng mở; chuỗi từ chối = 0

    link, _ = _send(world, uuid4())

    assert link.status is LinkStatus.PENDING and link.sharing_enabled is False


def test_error_messages_never_contain_code__AC17():
    caller = uuid4()
    scenarios = [World(owner=None), World(owner=caller), World(owner=uuid4(), consent=False)]
    locked = World(owner=uuid4())
    locked.state_value = ThrottleState(locked_until=NOW + timedelta(minutes=1))
    scenarios.append(locked)
    for world in scenarios:
        with pytest.raises(Exception) as exc:  # noqa: B017 - mọi nhánh lỗi
            _send(world, caller)
        assert CODE not in str(exc.value)
        assert CODE not in repr(exc.value.args)
        assert all(CODE not in str(arg) for failure in world.failures for arg in failure)


def test_code_passed_to_lookup_unchanged():
    world = World(owner=uuid4())

    _send(world, uuid4())

    assert world.looked_up == CODE
