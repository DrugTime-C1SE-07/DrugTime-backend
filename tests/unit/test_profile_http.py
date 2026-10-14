from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.modules.medication.adapters.inbound import profile_http as http
from drugtime.modules.medication.domain.user_condition import HealthProfile, UserConditionView
from drugtime.shared.db import get_uow
from drugtime.shared.errors import Conflict, Forbidden, NotFound

OPERATIONS = [
    ("get", "/profile", None),
    ("put", "/profile", {"full_name": "Bao", "date_of_birth": "2000-01-01", "gender": "nam"}),
    ("post", "/profile/conditions", {"condition_id": 1}),
    ("patch", "/profile/conditions/1", {"stage": None}),
    ("delete", "/profile/conditions/1", None),
]


@pytest.fixture
def client(monkeypatch):
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(uuid4(), False)

    @contextmanager
    def transaction():
        yield object()

    monkeypatch.setattr(http, "unit_of_work", transaction)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("method,path,body", OPERATIONS + [("get", "/conditions", None)])
def test_unauthenticated_all_operations(method, path, body):
    app = create_app()
    app.dependency_overrides[get_uow] = lambda: object()
    response = TestClient(app).request(method, path, json=body)
    assert response.status_code == 401


def test_get_no_store_nullable(client, monkeypatch):
    monkeypatch.setattr(http, "get_profile", lambda *a, **k: HealthProfile(None, None, None, []))
    response = client.get("/profile")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["full_name"] is None


@pytest.mark.parametrize("method,path,body", OPERATIONS)
def test_commit_failure_never_acknowledges_or_leaks(client, monkeypatch, method, path, body):
    events = []

    @contextmanager
    def fail_commit():
        events.append("begin")
        yield object()
        events.append("commit_failed")
        raise RuntimeError("private database details")

    monkeypatch.setattr(http, "unit_of_work", fail_commit)
    monkeypatch.setattr(
        http, "get_profile", lambda *a, **k: HealthProfile("Private", None, None, [])
    )
    monkeypatch.setattr(http, "update_profile", Mock())
    monkeypatch.setattr(
        http,
        "create_condition",
        lambda *a, **k: UserConditionView(1, 1, "Private disease", None, None),
    )
    monkeypatch.setattr(
        http,
        "update_condition",
        lambda *a, **k: UserConditionView(1, 1, "Private disease", None, None),
    )
    monkeypatch.setattr(http, "delete_condition", Mock())
    response = client.request(method, path, json=body)
    assert events == ["begin", "commit_failed"]
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


@pytest.mark.parametrize("method,path,body", OPERATIONS)
def test_denied_all_profile_operations(client, monkeypatch, method, path, body):
    def denied(*args, **kwargs):
        raise Forbidden("consent_revoked")

    for name in (
        "get_profile",
        "update_profile",
        "create_condition",
        "update_condition",
        "delete_condition",
    ):
        monkeypatch.setattr(http, name, denied)
    response = client.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json() == {"detail": "consent_revoked"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"full_name": " ", "date_of_birth": "2000-01-01", "gender": "nam"},
        {"full_name": "Bao", "date_of_birth": 0, "gender": "nam"},
        {"full_name": "Bao", "date_of_birth": "2000-01-01T00:00:00", "gender": "nam"},
    ],
)
def test_invalid_put_422(client, payload):
    assert client.put("/profile", json=payload).status_code == 422


@pytest.mark.parametrize("payload", [{}, {"condition_id": 2}, {"user_id": "other"}])
def test_patch_empty_or_unknown_422(client, payload):
    assert client.patch("/profile/conditions/1", json=payload).status_code == 422


@pytest.mark.parametrize("value", [0, -1, True, "1", 1.1, 9223372036854775808])
def test_create_invalid_id_422(client, value):
    assert client.post("/profile/conditions", json={"condition_id": value}).status_code == 422


def test_patch_null_versus_omitted(client, monkeypatch):
    update = Mock(return_value=UserConditionView(1, 4, "Diabetes", None, "old"))
    monkeypatch.setattr(http, "update_condition", update)
    response = client.patch("/profile/conditions/1", json={"subtype": None})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert update.call_args.kwargs["fields"] == {"subtype": None}


@pytest.mark.parametrize("method,path,body", [OPERATIONS[1], OPERATIONS[4]])
def test_204_bodyless(client, monkeypatch, method, path, body):
    monkeypatch.setattr(http, "update_profile", Mock())
    monkeypatch.setattr(http, "delete_condition", Mock())
    response = client.request(method, path, json=body)
    assert response.status_code == 204
    assert response.content == b""


def test_create_conflict_and_link_missing(client, monkeypatch):
    monkeypatch.setattr(
        http, "create_condition", Mock(side_effect=Conflict("condition_already_exists"))
    )
    assert client.post("/profile/conditions", json={"condition_id": 1}).status_code == 409
    monkeypatch.setattr(
        http, "delete_condition", Mock(side_effect=NotFound("user_condition_not_found"))
    )
    assert client.delete("/profile/conditions/99").json() == {"detail": "user_condition_not_found"}


def test_no_owner_selector(client):
    assert client.get("/profile?user_id=other").status_code == 422


@pytest.mark.parametrize("method,path,body", OPERATIONS + [("get", "/conditions", None)])
@pytest.mark.parametrize("kind", ["invalid", "erased"])
def test_invalid_or_erased_auth(method, path, body, kind, monkeypatch):
    from drugtime.modules.identity.adapters.inbound import dependencies

    app = create_app()
    app.dependency_overrides[get_uow] = lambda: object()
    if kind == "erased":
        monkeypatch.setattr(dependencies, "_decode", lambda _: {"sub": str(uuid4())})
        users = Mock()
        users.get.return_value = Mock(erased=True)
        monkeypatch.setattr(dependencies, "SqlUsers", lambda _: users)
    response = TestClient(app).request(
        method, path, json=body, headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_exact_int64_maximum_validated():
    from pydantic import ValidationError

    from drugtime.modules.medication.adapters.inbound.profile_schemas import (
        UserConditionCreateRequest,
    )

    assert UserConditionCreateRequest(condition_id=9223372036854775807).condition_id == (
        9223372036854775807
    )
    with pytest.raises(ValidationError):
        UserConditionCreateRequest(condition_id=9223372036854775808)


@pytest.mark.parametrize("commit_failure", [False, True])
def test_commit_precedes_asgi_response_start(monkeypatch, commit_failure):
    events = []

    @contextmanager
    def transaction():
        yield object()
        events.append("commit")
        if commit_failure:
            raise RuntimeError("commit failed")

    monkeypatch.setattr(http, "unit_of_work", transaction)
    monkeypatch.setattr(http, "get_profile", lambda *a, **k: HealthProfile(None, None, None, []))
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: identity.CurrentUser(uuid4(), False)

    async def observe(scope, receive, send):
        async def recorded_send(message):
            if message["type"] == "http.response.start":
                events.append(message["status"])
            await send(message)

        await app(scope, receive, recorded_send)

    response = TestClient(observe, raise_server_exceptions=False).get("/profile")
    status = 500 if commit_failure else 200
    assert response.status_code == status
    assert events == ["commit", status]


@pytest.mark.parametrize("model_name", ["UserConditionCreateRequest", "UserConditionUpdateRequest"])
@pytest.mark.parametrize("field", ["subtype", "stage"])
def test_nul_metadata_rejected_without_changing_schema(model_name, field):
    from pydantic import ValidationError

    from drugtime.modules.medication.adapters.inbound import profile_schemas

    model = getattr(profile_schemas, model_name)
    body = {"condition_id": 1} if model_name == "UserConditionCreateRequest" else {}
    with pytest.raises(ValidationError, match="NUL"):
        model.model_validate({**body, field: "text\x00value"})
    for value in (None, "", "  text\nwith spaces  "):
        assert getattr(model.model_validate({**body, field: value}), field) == value
