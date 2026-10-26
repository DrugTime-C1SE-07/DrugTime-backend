from contextlib import nullcontext
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity.adapters.inbound import http
from drugtime.modules.identity.adapters.outbound.sql_device_tokens import SqlDeviceTokens
from drugtime.modules.identity.application import manage_device_tokens
from drugtime.modules.identity.domain.user import CurrentUser
from drugtime.shared.db import get_uow
from drugtime.shared.errors import Conflict, Forbidden


def test_atomic_refresh_conflict_never_removes_old_token():
    uow = Mock()
    uow.connection.begin_nested.return_value = nullcontext()
    uow.connection.execute.return_value.first.return_value = None
    with pytest.raises(Conflict, match="device_token_in_use"):
        SqlDeviceTokens().register(uow, uuid4(), "new", "old")
    assert not any("DELETE" in str(c.args[0]) for c in uow.connection.execute.call_args_list)


def test_refresh_locks_in_stable_order_and_deletes_only_owned_previous():
    uow = Mock()
    user = uuid4()
    uow.connection.begin_nested.return_value = nullcontext()
    SqlDeviceTokens().register(uow, user, "new", "old")
    calls = uow.connection.execute.call_args_list
    assert [c.args[1]["t"] for c in calls[:2]] == ["new", "old"]
    assert "WHERE device_tokens.user_id = EXCLUDED.user_id" in str(calls[2].args[0])
    assert "WHERE user_id = :u AND fcm_token = :t" in str(calls[-1].args[0])
    assert calls[-1].args[1] == {"u": user, "t": "old"}


@pytest.mark.parametrize("operation", ["register", "unregister"])
def test_admin_never_mutates_tokens(operation):
    tokens = Mock()
    kwargs = dict(user_id=uuid4(), is_admin=True, fcm_token="test", tokens=tokens)
    if operation == "register":
        kwargs["previous_fcm_token"] = None
    with pytest.raises(Forbidden):
        getattr(manage_device_tokens, operation)(None, **kwargs)
    assert not tokens.mock_calls


@pytest.fixture
def client(monkeypatch):
    app = create_app()
    app.dependency_overrides[http.device_token_user] = lambda: CurrentUser(uuid4(), False)
    app.dependency_overrides[get_uow] = lambda: Mock()
    monkeypatch.setattr(http, "SqlDeviceTokens", Mock)
    return TestClient(app)


@pytest.mark.parametrize(
    "body",
    [
        {"fcm_token": "", "platform": "android"},
        {"fcm_token": "a b", "platform": "android"},
        {"fcm_token": "a", "platform": "ios"},
        {"fcm_token": "a", "platform": "android", "user_id": "other"},
    ],
)
def test_invalid_registration(client, body):
    assert client.put("/me/device-tokens", json=body).status_code == 422


def test_put_delete_body_and_empty_204(client):
    assert (
        client.put("/me/device-tokens", json={"fcm_token": "a", "platform": "android"}).status_code
        == 204
    )
    response = client.request("DELETE", "/me/device-tokens", json={"fcm_token": "a"})
    assert response.status_code == 204 and response.content == b""
