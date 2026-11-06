"""Unit test HTTP GET /patients/{patient_id}/food-interactions (task 4.05: AC9, AC16–AC18)."""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.identity import api as identity
from drugtime.modules.interaction.domain.evaluator import CheckResult
from drugtime.modules.interaction.domain.food_evaluator import (
    FOOD_DISCLAIMER,
    FoodMedicationResult,
    FoodReport,
    FoodWarning,
    IngredientRef,
    MedicationSummary,
)
from drugtime.shared.db import get_uow
from drugtime.shared.errors import Forbidden, NotFound

HTTP = "drugtime.modules.interaction.adapters.inbound.http"
AS_OF = datetime(2026, 11, 6, 3, 15, tzinfo=UTC)


def _fake_get_uow():
    yield MagicMock()


@contextmanager
def _fake_unit_of_work():
    yield MagicMock()


def _client(user=None):
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_get_uow
    if user is not None:
        app.dependency_overrides[identity.current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _report():
    x = IngredientRef(11, "Metronidazol")
    return FoodReport(
        status=CheckResult.FOUND,
        medications=(
            FoodMedicationResult(
                user_medication_id=42,
                medication=MedicationSummary(1007, "Rodogyl", "Spiramycin", "750", "Viên"),
                is_active=True,
                status=CheckResult.FOUND,
                ingredients=(x,),
                warnings=(FoodWarning(77, 912, x, "Rượu", 4, "Phản ứng", "Dược thư"),),
            ),
        ),
    )


def _get(client, patient_id, use_case, **params):
    with patch(f"{HTTP}.unit_of_work", _fake_unit_of_work), patch(
        f"{HTTP}.lookup_food_interactions", use_case
    ), patch(f"{HTTP}.now", return_value=AS_OF):
        return client.get(f"/patients/{patient_id}/food-interactions", params=params)


def test_401_without_token__AC17():
    r = _client().get(f"/patients/{uuid4()}/food-interactions")
    assert r.status_code == 401


@pytest.mark.parametrize(
    "path_id,params",
    [("abc", {}), (None, {"user_medication_id": "0"}), (None, {"user_medication_id": "-1"}),
     (None, {"user_medication_id": "x"})],
)
def test_422_bad_patient_id_or_user_medication_id__AC18(path_id, params):
    user = identity.CurrentUser(id=uuid4(), is_admin=False)
    use_case = MagicMock()
    r = _get(_client(user), path_id or user.id, use_case, **params)
    assert r.status_code == 422
    use_case.assert_not_called()


def test_200_shape_header_no_store_and_disclaimer__AC16_AC18():
    user = identity.CurrentUser(id=uuid4(), is_admin=False)
    use_case = MagicMock(return_value=_report())
    r = _get(_client(user), user.id, use_case)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"patient_id", "as_of", "status", "medications", "disclaimer"}
    assert body["patient_id"] == str(user.id)
    # AS_OF = 03:15 UTC → 10:15 giờ Việt Nam (bất biến 7, contract +07:00).
    assert body["as_of"] == "2026-11-06T10:15:00+07:00"
    assert body["status"] == "co_tuong_tac"
    assert body["disclaimer"] == FOOD_DISCLAIMER
    [m] = body["medications"]
    assert set(m) == {
        "user_medication_id", "medication", "is_active", "status", "ingredients", "warnings"
    }
    assert set(m["medication"]) == {
        "id", "name", "active_ingredient", "strength_text", "dosage_form"
    }
    assert m["warnings"] == [
        {
            "rule_id": 77,
            "version_id": 912,
            "ingredient": {"id": 11, "standard_name": "Metronidazol"},
            "food_to_avoid": "Rượu",
            "severity_level": 4,
            "reason": "Phản ứng",
            "source": "Dược thư",
        }
    ]
    kwargs = use_case.call_args.kwargs
    assert kwargs["caller_id"] == user.id and kwargs["patient_id"] == user.id
    assert kwargs["user_medication_id"] is None


def test_filter_passed_through__AC8():
    user = identity.CurrentUser(id=uuid4(), is_admin=False)
    use_case = MagicMock(return_value=FoodReport(CheckResult.INSUFFICIENT_DATA, ()))
    r = _get(_client(user), user.id, use_case, user_medication_id="42")
    assert r.status_code == 200
    assert use_case.call_args.kwargs["user_medication_id"] == 42


def test_404_maps_to_user_medication_not_found__AC9():
    user = identity.CurrentUser(id=uuid4(), is_admin=False)
    use_case = MagicMock(side_effect=NotFound("user_medication_not_found"))
    r = _get(_client(user), user.id, use_case, user_medication_id="5")
    assert r.status_code == 404
    assert r.json() == {"detail": "user_medication_not_found"}


def test_403_from_pep__AC12():
    user = identity.CurrentUser(id=uuid4(), is_admin=False)
    use_case = MagicMock(side_effect=Forbidden("khong_co_quyen"))
    r = _get(_client(user), uuid4(), use_case)
    assert r.status_code == 403
    assert r.json() == {"detail": "khong_co_quyen"}


def test_access_log_failure_is_500_without_data__AC14b():
    user = identity.CurrentUser(id=uuid4(), is_admin=False)
    use_case = MagicMock(side_effect=RuntimeError("access_logs unavailable"))
    r = _get(_client(user), user.id, use_case)
    assert r.status_code == 500
    assert "medications" not in r.text
