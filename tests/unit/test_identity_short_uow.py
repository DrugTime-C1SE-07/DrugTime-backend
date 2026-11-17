from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from drugtime.modules.identity.adapters.inbound import dependencies
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.errors import Unauthorized


def test_short_auth_releases_connection_and_shared_auth_uses_supplied_uow(monkeypatch):
    user_id = uuid4()
    events = []
    uow = object()

    @contextmanager
    def transaction():
        events.append("checkout")
        try:
            yield uow
        finally:
            events.append("checkin")

    def lookup(actual_uow):
        assert actual_uow is uow

        def get(lookup_id):
            assert lookup_id == user_id
            events.append("lookup")
            return SimpleNamespace(id=user_id, is_admin=False, erased=False)

        return SimpleNamespace(get=get)

    monkeypatch.setattr(dependencies, "read_unit_of_work", transaction)
    monkeypatch.setattr(dependencies, "SqlUsers", lookup)
    monkeypatch.setattr(dependencies, "_decode", lambda _: {"sub": str(user_id)})

    assert dependencies.current_user_short_uow("Bearer token") == CurrentUser(user_id, False)
    assert events == ["checkout", "lookup", "checkin"]

    events.clear()
    assert dependencies.current_user("Bearer token", uow) == CurrentUser(user_id, False)
    assert events == ["lookup"]


@pytest.mark.parametrize("header", [None, "Basic token", "Bearer", "Bearer invalid"])
def test_short_auth_rejects_invalid_bearer_before_checkout(monkeypatch, header):
    def reject(_token):
        raise Unauthorized("Invalid bearer token")

    def unexpected_checkout():
        pytest.fail("Invalid credentials must not check out a connection")

    monkeypatch.setattr(dependencies, "_decode", reject)
    monkeypatch.setattr(dependencies, "read_unit_of_work", unexpected_checkout)
    with pytest.raises(Unauthorized):
        dependencies.current_user_short_uow(header)
