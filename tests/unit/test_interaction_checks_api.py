"""Unit tests cho endpoint POST /patients/{patient_id}/interaction-checks (PB24, Task 4.02)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from drugtime.main import create_app
from drugtime.modules.catalog.domain.medication import CatalogMedication
from drugtime.modules.identity import api as identity
from drugtime.modules.interaction.domain.catalog_rules import (
    DrugInteractionContent,
    HandlingType,
    InteractionType,
    RuleRecord,
)
from drugtime.modules.interaction.domain.evaluator import NFR03_DISCLAIMER
from drugtime.shared.db import get_uow
from drugtime.shared.errors import Forbidden

HTTP = "drugtime.modules.interaction.adapters.inbound.http"
APP_SERVICE = "drugtime.modules.interaction.application.check_patient_interactions"


def _fake_uow():
    yield MagicMock()


def _client(user=None):
    app = create_app()
    app.dependency_overrides[get_uow] = _fake_uow
    if user is not None:
        app.dependency_overrides[identity.current_user] = lambda: user
    return TestClient(app)


def test_interaction_checks_unauthenticated():
    client = _client(user=None)
    patient_id = uuid4()
    resp = client.post(f"/patients/{patient_id}/interaction-checks", json={})
    assert resp.status_code == 401


def test_interaction_checks_forbidden_by_access_control():
    caller = identity.CurrentUser(id=uuid4(), is_admin=False)
    client = _client(user=caller)
    patient_id = uuid4()

    with patch(f"{APP_SERVICE}.access.authorize", side_effect=Forbidden("khong_co_quyen")):
        resp = client.post(f"/patients/{patient_id}/interaction-checks", json={})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "khong_co_quyen"


def test_interaction_checks_candidate_medication_not_found():
    caller = identity.CurrentUser(id=uuid4(), is_admin=False)
    client = _client(user=caller)
    patient_id = caller.id

    with patch(f"{APP_SERVICE}.access.authorize"), patch(
        f"{APP_SERVICE}.catalog.get_medication", return_value=None
    ):
        resp = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={"candidate_medication_id": 999999},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "catalog_medication_not_found"


def test_interaction_checks_none_found():
    patient_id = uuid4()
    caller = identity.CurrentUser(id=patient_id, is_admin=False)
    client = _client(user=caller)

    med_a = CatalogMedication(
        id=10,
        name="Paracetamol 500mg",
        strength_text="500mg",
        dosage_form="Viên nén",
        has_active_ingredients=True,
    )
    med_b = CatalogMedication(
        id=20,
        name="Vitamin C 500mg",
        strength_text="500mg",
        dosage_form="Viên nén",
        has_active_ingredients=True,
    )

    def mock_get_medication(uow, med_id, include_deleted=True):
        return med_a if med_id == 10 else med_b

    def mock_ingredient_ids(uow, med_id):
        return [101] if med_id == 10 else [102]

    with patch(f"{APP_SERVICE}.access.authorize"), patch(
        f"{APP_SERVICE}.catalog.get_medication", side_effect=mock_get_medication
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_ids_of_medication", side_effect=mock_ingredient_ids
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_names",
        return_value={101: "Paracetamol", 102: "Acid ascorbic"},
    ), patch(
        f"{APP_SERVICE}.SqlDrugInteractions.active_rules_for_ingredients", return_value=[]
    ):
        resp = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={"candidate_medication_id": 10, "medication_ids": [20]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "da_kiem_tra_khong_thay"
        assert data["interactions"] == []
        assert data["insufficient_data_medications"] == []
        assert data["disclaimer"] == NFR03_DISCLAIMER


def test_interaction_checks_found_interaction_with_severity():
    patient_id = uuid4()
    caller = identity.CurrentUser(id=patient_id, is_admin=False)
    client = _client(user=caller)

    med_a = CatalogMedication(
        id=100,
        name="Lopid 600mg",
        strength_text="600mg",
        dosage_form="Viên nén",
        has_active_ingredients=True,
    )
    med_b = CatalogMedication(
        id=200,
        name="Lipobay 0.3mg",
        strength_text="0.3mg",
        dosage_form="Viên nén",
        has_active_ingredients=True,
    )

    rule = RuleRecord(
        content=DrugInteractionContent(
            ingredient_a_id=1,
            ingredient_b_id=2,
            ingredient_b_external_name=None,
            interaction_type=InteractionType.CONTRAINDICATED,
            severity_level=4,
            handling_type=HandlingType.AVOID,
            min_interval_hours=None,
            description="Nguy cơ tiêu cơ vân kịch phát và tử vong.",
            source="Dược thư Quốc gia Việt Nam",
        ),
        meta=MagicMock(),
    )

    def mock_get_medication(uow, med_id, include_deleted=True):
        return med_a if med_id == 100 else med_b

    def mock_ingredient_ids(uow, med_id):
        return [1] if med_id == 100 else [2]

    with patch(f"{APP_SERVICE}.access.authorize"), patch(
        f"{APP_SERVICE}.catalog.get_medication", side_effect=mock_get_medication
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_ids_of_medication", side_effect=mock_ingredient_ids
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_names",
        return_value={1: "Gemfibrozil", 2: "Cerivastatin"},
    ), patch(
        f"{APP_SERVICE}.SqlDrugInteractions.active_rules_for_ingredients", return_value=[rule]
    ):
        resp = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={"candidate_medication_id": 100, "medication_ids": [200]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "co_tuong_tac"
        assert len(data["interactions"]) == 1
        finding = data["interactions"][0]
        assert finding["severity_level"] == 4
        assert finding["interaction_type"] == "chong_chi_dinh"
        assert finding["handling_type"] == "tranh_phoi_hop"
        assert "[CHỐNG CHỈ ĐỊNH]" in finding["warning_message"]
        assert finding["medication_a_id"] == 100
        assert finding["medication_b_id"] == 200
        assert data["disclaimer"] == NFR03_DISCLAIMER


def test_interaction_checks_insufficient_data():
    patient_id = uuid4()
    caller = identity.CurrentUser(id=patient_id, is_admin=False)
    client = _client(user=caller)

    med_a = CatalogMedication(
        id=300,
        name="Thảo dược Nam Y",
        strength_text=None,
        dosage_form="Gói bột",
        has_active_ingredients=False,
    )

    with patch(f"{APP_SERVICE}.access.authorize"), patch(
        f"{APP_SERVICE}.catalog.get_medication", return_value=med_a
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_ids_of_medication", return_value=[]
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_names", return_value={}
    ), patch(
        f"{APP_SERVICE}.SqlDrugInteractions.active_rules_for_ingredients", return_value=[]
    ):
        resp = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={"candidate_medication_id": 300},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "khong_du_du_lieu"
        assert len(data["insufficient_data_medications"]) == 1
        assert data["insufficient_data_medications"][0]["medication_id"] == 300
        assert data["disclaimer"] == NFR03_DISCLAIMER


def test_interaction_checks_with_dose_threshold():
    from drugtime.modules.interaction.domain.catalog_rules import DoseThreshold

    patient_id = uuid4()
    caller = identity.CurrentUser(id=patient_id, is_admin=False)
    client = _client(user=caller)

    med_a = CatalogMedication(
        id=400,
        name="Simvastatin 40mg",
        strength_text="40mg",
        dosage_form="Viên nén",
        has_active_ingredients=True,
    )
    med_b = CatalogMedication(
        id=401,
        name="Amlodipine 5mg",
        strength_text="5mg",
        dosage_form="Viên nén",
        has_active_ingredients=True,
    )

    threshold = DoseThreshold(
        ingredient_ref="A",
        min_dose=40.0,
        max_dose=None,
        dose_unit="mg",
        severity_level=3,
        warning_text="Simvastatin liều từ 40mg tăng nguy cơ tổn thương cơ khi phối hợp Amlodipine.",
    )
    rule = RuleRecord(
        content=DrugInteractionContent(
            ingredient_a_id=501,
            ingredient_b_id=502,
            ingredient_b_external_name=None,
            interaction_type=InteractionType.DOSE_DEPENDENT,
            severity_level=2,
            handling_type=HandlingType.MONITOR,
            min_interval_hours=None,
            description="Tăng nồng độ Simvastatin.",
            source="Dược thư Quốc gia Việt Nam",
            dose_thresholds=(threshold,),
        ),
        meta=MagicMock(),
    )

    def mock_get_medication(uow, med_id, include_deleted=True):
        return med_a if med_id == 400 else med_b

    def mock_ingredient_ids(uow, med_id):
        return [501] if med_id == 400 else [502]

    with patch(f"{APP_SERVICE}.access.authorize"), patch(
        f"{APP_SERVICE}.catalog.get_medication", side_effect=mock_get_medication
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_ids_of_medication", side_effect=mock_ingredient_ids
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_names",
        return_value={501: "Simvastatin", 502: "Amlodipine"},
    ), patch(
        f"{APP_SERVICE}.SqlDrugInteractions.active_rules_for_ingredients", return_value=[rule]
    ):
        # 1. Liều cao (candidate_dose_amount = 40.0) -> Kích hoạt ngưỡng liều: Severity 3
        resp_high = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={
                "candidate_medication_id": 400,
                "candidate_dose_amount": 40.0,
                "candidate_dose_unit": "mg",
                "medication_ids": [401],
            },
        )
        assert resp_high.status_code == 200
        data_high = resp_high.json()
        assert data_high["status"] == "co_tuong_tac"
        assert len(data_high["interactions"]) == 1
        assert data_high["interactions"][0]["severity_level"] == 3
        assert (
            data_high["interactions"][0]["warning_message"]
            == "Simvastatin liều từ 40mg tăng nguy cơ tổn thương cơ khi phối hợp Amlodipine."
        )

        # 2. Liều thấp (candidate_dose_amount = 20.0) -> Severity 2 mặc định
        resp_low = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={
                "candidate_medication_id": 400,
                "candidate_dose_amount": 20.0,
                "candidate_dose_unit": "mg",
                "medication_ids": [401],
            },
        )
        assert resp_low.status_code == 200
        data_low = resp_low.json()
        assert data_low["status"] == "co_tuong_tac"
        assert len(data_low["interactions"]) == 1
        assert data_low["interactions"][0]["severity_level"] == 2

        # 3. Liều cao nhưng đơn vị không tương thích ("viên" vs "mg") -> Giữ Severity 2 mặc định
        resp_incompatible = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={
                "candidate_medication_id": 400,
                "candidate_dose_amount": 40.0,
                "candidate_dose_unit": "viên",
                "medication_ids": [401],
            },
        )
        assert resp_incompatible.status_code == 200
        data_incompatible = resp_incompatible.json()
        assert data_incompatible["interactions"][0]["severity_level"] == 2

        # 4. Liều cao nhưng thiếu đơn vị (candidate_dose_unit = null) -> Giữ Severity 2 mặc định
        resp_missing_unit = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={
                "candidate_medication_id": 400,
                "candidate_dose_amount": 40.0,
                "medication_ids": [401],
            },
        )
        assert resp_missing_unit.status_code == 200
        data_missing = resp_missing_unit.json()
        assert data_missing["interactions"][0]["severity_level"] == 2


def test_interaction_checks_preserves_existing_medication_doses_with_medication_ids():
    patient_id = uuid4()
    caller = identity.CurrentUser(id=patient_id, is_admin=False)

    fake_uow = MagicMock()
    # Mock user_medications query returning medication_id=200, quantity_per_dose=2.0
    mock_row = MagicMock()
    mock_row.medication_id = 200
    mock_row.quantity_per_dose = 2.0
    fake_uow.connection.execute.return_value.all.return_value = [mock_row]

    def _custom_fake_uow():
        yield fake_uow

    app = create_app()
    app.dependency_overrides[get_uow] = _custom_fake_uow
    app.dependency_overrides[identity.current_user] = lambda: caller
    client = TestClient(app)

    med_a = CatalogMedication(
        id=100,
        name="Thuốc A",
        strength_text="10mg",
        dosage_form="Viên",
        has_active_ingredients=True,
    )
    med_b = CatalogMedication(
        id=200,
        name="Thuốc B",
        strength_text="20mg",
        dosage_form="Viên",
        has_active_ingredients=True,
    )

    def mock_get_med(uow, med_id, include_deleted=True):
        return med_a if med_id == 100 else med_b

    def mock_ing_ids(uow, med_id):
        return [1] if med_id == 100 else [2]

    with patch(f"{APP_SERVICE}.access.authorize"), patch(
        f"{APP_SERVICE}.catalog.get_medication", side_effect=mock_get_med
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_ids_of_medication", side_effect=mock_ing_ids
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_names", return_value={1: "Hoạt chất A", 2: "Hoạt chất B"}
    ), patch(
        f"{APP_SERVICE}.SqlDrugInteractions.active_rules_for_ingredients", return_value=[]
    ), patch(
        f"{APP_SERVICE}.evaluate"
    ) as mock_evaluate:
        mock_evaluate.return_value = MagicMock(
            status=MagicMock(value="da_kiem_tra_khong_thay"),
            interactions=(),
            insufficient_data_medications=(),
            disclaimer=NFR03_DISCLAIMER,
        )

        resp = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={"candidate_medication_id": 100, "medication_ids": [200]},
        )
        assert resp.status_code == 200

        # Xác minh evaluate nhận đúng EvaluatedMedication với dose_amount=2.0 từ DB
        mock_evaluate.assert_called_once()
        evaluated_meds = mock_evaluate.call_args[0][0]
        med200 = next(m for m in evaluated_meds if m.medication_id == 200)
        assert med200.dose_amount == 2.0
        assert med200.dose_unit is None  # Không gán bừa đơn vị mg khi DB không lưu


def test_interaction_checks_mixed_response():
    patient_id = uuid4()
    caller = identity.CurrentUser(id=patient_id, is_admin=False)
    client = _client(user=caller)

    med_a = CatalogMedication(
        id=100,
        name="Thuốc A",
        strength_text="100mg",
        dosage_form="Viên",
        has_active_ingredients=True,
    )
    med_b = CatalogMedication(
        id=200,
        name="Thuốc B",
        strength_text="200mg",
        dosage_form="Viên",
        has_active_ingredients=True,
    )
    med_c = CatalogMedication(
        id=300,
        name="Thuốc Đông Y Không Rõ Hoạt Chất",
        strength_text=None,
        dosage_form="Gói bột",
        has_active_ingredients=False,
    )

    rule = RuleRecord(
        content=DrugInteractionContent(
            ingredient_a_id=1,
            ingredient_b_id=2,
            ingredient_b_external_name=None,
            interaction_type=InteractionType.CONTRAINDICATED,
            severity_level=4,
            handling_type=HandlingType.AVOID,
            min_interval_hours=None,
            description="Tương tác chống chỉ định.",
            source="Dược thư Quốc gia Việt Nam",
        ),
        meta=MagicMock(),
    )

    def mock_get_medication(uow, med_id, include_deleted=True):
        if med_id == 100:
            return med_a
        if med_id == 200:
            return med_b
        return med_c

    def mock_ingredient_ids(uow, med_id):
        if med_id == 100:
            return [1]
        if med_id == 200:
            return [2]
        return []

    with patch(f"{APP_SERVICE}.access.authorize"), patch(
        f"{APP_SERVICE}.catalog.get_medication", side_effect=mock_get_medication
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_ids_of_medication", side_effect=mock_ingredient_ids
    ), patch(
        f"{APP_SERVICE}.catalog.ingredient_names",
        return_value={1: "Hoạt chất 1", 2: "Hoạt chất 2"},
    ), patch(
        f"{APP_SERVICE}.SqlDrugInteractions.active_rules_for_ingredients", return_value=[rule]
    ):
        resp = client.post(
            f"/patients/{patient_id}/interaction-checks",
            json={"candidate_medication_id": 100, "medication_ids": [200, 300]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "co_tuong_tac"
        assert len(data["interactions"]) == 1
        assert data["interactions"][0]["severity_level"] == 4
        assert len(data["insufficient_data_medications"]) == 1
        assert data["insufficient_data_medications"][0]["medication_id"] == 300
        assert data["disclaimer"] == NFR03_DISCLAIMER



