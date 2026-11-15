from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.modules.medication.adapters.inbound import health_setup_http as http
from drugtime.modules.medication.domain.health_setup import HealthSetup, SetupStep
from drugtime.shared.errors import Forbidden


def test_get_snapshot_does_not_cache_and_protects_before_reading(monkeypatch):
    user = identity.CurrentUser(uuid4(), False)
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: user
    authorize = Mock()
    read = Mock(return_value=HealthSetup("0", SetupStep("unreported"), SetupStep("none_known")))

    @contextmanager
    def uow():
        yield object()

    monkeypatch.setattr(http, "unit_of_work", uow)
    monkeypatch.setattr(http._ACCESS, "authorize_setup", authorize)
    monkeypatch.setattr(http, "read_setup", read)

    with TestClient(app) as client:
        response = client.get("/profile/health-setup")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["conditions"] == {"status": "none_known"}
        authorize.side_effect = Forbidden("khong_co_quyen")
        response = client.get("/profile/health-setup", params={"patient_id": str(uuid4())})
        assert response.status_code == 403
        assert authorize.call_args.kwargs["rejected_owner_selector"] is True
        read.assert_called_once()


def test_put_declares_expected_response_codes_and_authentication():
    spec = create_app().openapi()
    operation = spec["paths"]["/profile/health-setup"]["put"]
    assert operation["operationId"] == "replaceOwnHealthSetupSteps"
    assert operation["security"] == [{"bearerAuth": []}]
    assert set(operation["responses"]) == {"200", "401", "403", "409", "422", "500"}
    assert operation["requestBody"]["required"] is True
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["required"] == ["revision"]
    assert schema["additionalProperties"] is False
    for step in ("allergies", "conditions"):
        options = schema["properties"][step]["anyOf"]
        for option in options:
            if "$ref" in option:
                assert option["$ref"].rsplit("/", 1)[-1] in spec["components"]["schemas"]


@pytest.mark.parametrize("body", [b"{}", b"{", b""])
def test_put_authorization_precedes_payload_validation(monkeypatch, body):
    user = identity.CurrentUser(uuid4(), False)
    app = create_app()
    app.dependency_overrides[identity.current_user] = lambda: user
    authorize = Mock(side_effect=Forbidden("khong_co_quyen"))
    save = Mock()

    @contextmanager
    def uow():
        yield object()

    monkeypatch.setattr(http, "unit_of_work", uow)
    monkeypatch.setattr(http._ACCESS, "authorize_setup", authorize)
    monkeypatch.setattr(http, "save_setup", save)

    with TestClient(app) as client:
        response = client.put(
            "/profile/health-setup",
            params={"patient_id": str(uuid4())},
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 403
        assert response.json() == {"detail": "khong_co_quyen"}
        authorize.assert_called_once()
        assert authorize.call_args.kwargs["rejected_owner_selector"] is True

        authorize.side_effect = None
        response = client.put(
            "/profile/health-setup",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert "input" not in response.json()["detail"][0]
        assert authorize.call_count == 2
        save.assert_not_called()
