from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from drugtime.modules.identity import api as identity
from drugtime.modules.interaction.adapters.inbound.schemas import (
    DrugFoodInteraction,
    DrugFoodInteractionCreate,
    DrugFoodInteractionPage,
    DrugFoodInteractionUpdate,
    DrugFoodInteractionVersionList,
    DrugInteraction,
    DrugInteractionCreate,
    DrugInteractionPage,
    DrugInteractionUpdate,
    DrugInteractionVersionList,
    ErrorDetail,
    FoodInteractionReport,
    InsufficientDataMedication,
    InteractionCheckRequest,
    InteractionCheckResponse,
    InteractionCheckStatus,
    PatientInteractionFinding,
)
from drugtime.modules.interaction.adapters.outbound.other_modules import (
    CatalogIngredients,
    CatalogMedications,
    IdentityAdmins,
    PatientMedications,
)
from drugtime.modules.interaction.adapters.outbound.sql_interaction_rules import (
    SqlDrugFoodInteractions,
    SqlDrugInteractions,
)
from drugtime.modules.interaction.application.check_patient_interactions import (
    check_patient_interactions,
)
from drugtime.modules.interaction.application.lookup_food_interactions import (
    lookup_food_interactions,
)
from drugtime.modules.interaction.application.manage_drug_food_interactions import (
    drug_food_interaction_service,
)
from drugtime.modules.interaction.application.manage_drug_interactions import (
    drug_interaction_service,
)
from drugtime.modules.interaction.application.manage_rules import ListQuery
from drugtime.modules.interaction.domain.catalog_rules import InteractionType
from drugtime.shared.clock import now
from drugtime.shared.db import SqlUnitOfWork, get_uow, unit_of_work

router = APIRouter(tags=["interaction"])

UowDep = Annotated[SqlUnitOfWork, Depends(get_uow)]

# Đăng ký với tests/architecture/test_health_route_enforcement.py (task 4.05, G15).
_HEALTH_EXTRA = {"x-health-scope": "canh_bao_tuong_tac", "x-health-audit-self": True}
# Chỉ để OpenAPI khai báo `security: bearerAuth`; xác thực thật ở identity.current_user.
_BEARER = Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
_NO_STORE = {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}

@router.post(
    "/patients/{patient_id}/interaction-checks",
    response_model=InteractionCheckResponse,
    responses={
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        403: {"model": ErrorDetail, "description": "khong_co_quyen | consent_revoked"},
        422: {"description": "ValidationError | ErrorDetail catalog_medication_not_found"},
    },
    operation_id="checkPatientInteractions",
    summary="Kiểm tra tương tác thuốc của người bệnh (PB24, Task 4.02)",
    openapi_extra=_HEALTH_EXTRA,
    dependencies=[_BEARER],
)
def check_interactions_endpoint(
    patient_id: UUID,
    body: InteractionCheckRequest,
    user: Annotated[identity.CurrentUser, Depends(identity.current_user)],
) -> JSONResponse:
    # Fail-closed (task 4.05, AC24): dựng response trong transaction, nên dòng access_logs
    # `allowed` commit xong mới trả dữ liệu. `Depends(get_uow)` commit sau khi đã gửi response.
    with unit_of_work() as uow:
        res = check_patient_interactions(
            uow,
            caller_id=user.id,
            caller_is_admin=user.is_admin,
            patient_id=patient_id,
            candidate_medication_id=body.candidate_medication_id,
            candidate_dose_amount=body.candidate_dose_amount,
            candidate_dose_unit=body.candidate_dose_unit,
            medication_ids=body.medication_ids,
        )
        payload = _interaction_check_response(res).model_dump(mode="json")
        response = JSONResponse(payload)
    return response


def _interaction_check_response(res) -> InteractionCheckResponse:
    return InteractionCheckResponse(
        status=InteractionCheckStatus(res.status.value),
        interactions=[
            PatientInteractionFinding(
                ingredient_a_id=f.ingredient_a_id,
                ingredient_a_name=f.ingredient_a_name,
                ingredient_b_id=f.ingredient_b_id,
                ingredient_b_name=f.ingredient_b_name,
                medication_a_id=f.medication_a_id,
                medication_a_name=f.medication_a_name,
                medication_b_id=f.medication_b_id,
                medication_b_name=f.medication_b_name,
                severity_level=f.severity_level,
                interaction_type=f.interaction_type,
                handling_type=f.handling_type,
                min_interval_hours=f.min_interval_hours,
                description=f.description,
                warning_message=f.warning_message,
                source=f.source,
            )
            for f in res.interactions
        ],
        insufficient_data_medications=[
            InsufficientDataMedication(
                medication_id=m.medication_id,
                medication_name=m.medication_name,
                reason=m.reason,
            )
            for m in res.insufficient_data_medications
        ],
        disclaimer=res.disclaimer,
    )


@router.get(
    "/patients/{patient_id}/food-interactions",
    response_model=FoodInteractionReport,
    responses={
        200: {"headers": _NO_STORE},
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        403: {"model": ErrorDetail, "description": "khong_co_quyen | consent_revoked"},
        404: {"model": ErrorDetail, "description": "user_medication_not_found"},
    },
    operation_id="listPatientFoodInteractions",
    summary="Tra cứu thực phẩm cần tránh cho thuốc của người bệnh (PB25, Task 4.05)",
    openapi_extra=_HEALTH_EXTRA,
    dependencies=[_BEARER],
)
def list_food_interactions_endpoint(
    patient_id: UUID,
    user: Annotated[identity.CurrentUser, Depends(identity.current_user)],
    user_medication_id: Annotated[int | None, Query(ge=1)] = None,
) -> JSONResponse:
    as_of = now()
    # Dựng response trong transaction: dòng access_logs `allowed` commit trước khi trả dữ liệu.
    with unit_of_work() as uow:
        report = lookup_food_interactions(
            uow,
            caller_id=user.id,
            caller_is_admin=user.is_admin,
            patient_id=patient_id,
            user_medication_id=user_medication_id,
            medications=PatientMedications(),
            catalog=CatalogMedications(),
            ingredients=CatalogIngredients(),
            rules=SqlDrugFoodInteractions(),
        )
        payload = FoodInteractionReport.model_validate(
            {
                "patient_id": patient_id,
                "as_of": as_of,
                "status": report.status.value,
                "medications": [asdict(m) for m in report.medications],
                "disclaimer": report.disclaimer,
            }
        ).model_dump(mode="json")
        response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
    return response


AdminDep = Annotated[identity.CurrentUser, Depends(identity.require_admin)]
Severity = Annotated[int | None, Query(ge=1, le=4)]
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
Q = Annotated[str | None, Query(min_length=1, max_length=100)]
ExpectedVersion = Annotated[int, Query(ge=1)]

_ERRORS = {
    401: {"model": ErrorDetail, "description": "Chưa xác thực"},
    403: {"model": ErrorDetail, "description": "Chỉ Admin (`admin_only`)"},
}
_NOT_FOUND = {404: {"model": ErrorDetail, "description": "`interaction_rule_not_found`"}}
_CONFLICT = {
    409: {"model": ErrorDetail, "description": "`interaction_rule_exists` | `version_conflict`"}
}


def _ddi():
    return drug_interaction_service(SqlDrugInteractions(), CatalogIngredients(), IdentityAdmins())


def _food():
    return drug_food_interaction_service(
        SqlDrugFoodInteractions(), CatalogIngredients(), IdentityAdmins()
    )


# ============================================================================
# Admin Dashboard / Quy tắc tương tác giữa hai hoạt chất (PB05, Task 2.16)
# ============================================================================


@router.post(
    "/admin/drug-interactions",
    response_model=DrugInteraction,
    status_code=status.HTTP_201_CREATED,
    responses={**_ERRORS, **_CONFLICT},
    operation_id="createDrugInteraction",
    summary="Admin: thêm quy tắc tương tác giữa hai hoạt chất",
)
def create_drug_interaction(
    payload: DrugInteractionCreate, uow: UowDep, admin: AdminDep
) -> DrugInteraction:
    return DrugInteraction.from_view(_ddi().create(uow, admin.id, payload.to_domain()))


@router.get(
    "/admin/drug-interactions",
    response_model=DrugInteractionPage,
    responses=_ERRORS,
    operation_id="listDrugInteractions",
    summary="Admin: danh sách quy tắc tương tác giữa hai hoạt chất",
)
def list_drug_interactions(
    uow: UowDep,
    _admin: AdminDep,
    q: Q = None,
    ingredient_id: int | None = None,
    medication_id: int | None = None,
    interaction_type: InteractionType | None = None,
    severity_level: Severity = None,
    skip: Skip = 0,
    limit: Limit = 20,
) -> DrugInteractionPage:
    views, total = _ddi().list(
        uow,
        ListQuery(
            q=q,
            ingredient_id=ingredient_id,
            medication_id=medication_id,
            interaction_type=interaction_type.value if interaction_type else None,
            severity_level=severity_level,
            skip=skip,
            limit=limit,
        ),
    )
    return DrugInteractionPage(items=[DrugInteraction.from_view(v) for v in views], total=total)


@router.get(
    "/admin/drug-interactions/{id}",
    response_model=DrugInteraction,
    responses={**_ERRORS, **_NOT_FOUND},
    operation_id="getDrugInteraction",
    summary="Admin: chi tiết quy tắc (phiên bản hiện hành)",
)
def get_drug_interaction(id: int, uow: UowDep, _admin: AdminDep) -> DrugInteraction:
    return DrugInteraction.from_view(_ddi().get(uow, id))


@router.patch(
    "/admin/drug-interactions/{id}",
    response_model=DrugInteraction,
    responses={**_ERRORS, **_NOT_FOUND, **_CONFLICT},
    operation_id="updateDrugInteraction",
    summary="Admin: sửa quy tắc (tạo phiên bản mới)",
)
def update_drug_interaction(
    id: int, payload: DrugInteractionUpdate, uow: UowDep, admin: AdminDep
) -> DrugInteraction:
    view = _ddi().update(uow, admin.id, id, payload.expected_version, payload.changes())
    return DrugInteraction.from_view(view)


@router.delete(
    "/admin/drug-interactions/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={**_ERRORS, **_NOT_FOUND, **_CONFLICT},
    operation_id="deleteDrugInteraction",
    summary="Admin: xóa mềm quy tắc",
)
def delete_drug_interaction(
    id: int, expected_version: ExpectedVersion, uow: UowDep, admin: AdminDep
) -> Response:
    _ddi().delete(uow, admin.id, id, expected_version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/admin/drug-interactions/{id}/versions",
    response_model=DrugInteractionVersionList,
    responses={**_ERRORS, **_NOT_FOUND},
    operation_id="listDrugInteractionVersions",
    summary="Admin: lịch sử phiên bản của quy tắc",
)
def list_drug_interaction_versions(
    id: int, uow: UowDep, _admin: AdminDep
) -> DrugInteractionVersionList:
    return DrugInteractionVersionList(
        items=[DrugInteraction.from_view(v) for v in _ddi().history(uow, id)]
    )


@router.get(
    "/admin/drug-interaction-versions/{version_id}",
    response_model=DrugInteraction,
    responses={
        **_ERRORS,
        404: {"model": ErrorDetail, "description": "`interaction_version_not_found`"},
    },
    operation_id="getDrugInteractionVersion",
    summary="Admin: xem một phiên bản theo id phiên bản",
)
def get_drug_interaction_version(version_id: int, uow: UowDep, _admin: AdminDep) -> DrugInteraction:
    return DrugInteraction.from_view(_ddi().get_version(uow, version_id))


# ============================================================================
# Admin Dashboard / Quy tắc tương tác hoạt chất–thực phẩm (PB05, Task 2.16)
# ============================================================================


@router.post(
    "/admin/drug-food-interactions",
    response_model=DrugFoodInteraction,
    status_code=status.HTTP_201_CREATED,
    responses={**_ERRORS, **_CONFLICT},
    operation_id="createDrugFoodInteraction",
    summary="Admin: thêm quy tắc tương tác hoạt chất–thực phẩm",
)
def create_drug_food_interaction(
    payload: DrugFoodInteractionCreate, uow: UowDep, admin: AdminDep
) -> DrugFoodInteraction:
    return DrugFoodInteraction.from_view(_food().create(uow, admin.id, payload.to_domain()))


@router.get(
    "/admin/drug-food-interactions",
    response_model=DrugFoodInteractionPage,
    responses=_ERRORS,
    operation_id="listDrugFoodInteractions",
    summary="Admin: danh sách quy tắc tương tác hoạt chất–thực phẩm",
)
def list_drug_food_interactions(
    uow: UowDep,
    _admin: AdminDep,
    q: Q = None,
    ingredient_id: int | None = None,
    medication_id: int | None = None,
    severity_level: Severity = None,
    skip: Skip = 0,
    limit: Limit = 20,
) -> DrugFoodInteractionPage:
    views, total = _food().list(
        uow,
        ListQuery(
            q=q,
            ingredient_id=ingredient_id,
            medication_id=medication_id,
            severity_level=severity_level,
            skip=skip,
            limit=limit,
        ),
    )
    return DrugFoodInteractionPage(
        items=[DrugFoodInteraction.from_view(v) for v in views], total=total
    )


@router.get(
    "/admin/drug-food-interactions/{id}",
    response_model=DrugFoodInteraction,
    responses={**_ERRORS, **_NOT_FOUND},
    operation_id="getDrugFoodInteraction",
    summary="Admin: chi tiết quy tắc hoạt chất–thực phẩm",
)
def get_drug_food_interaction(id: int, uow: UowDep, _admin: AdminDep) -> DrugFoodInteraction:
    return DrugFoodInteraction.from_view(_food().get(uow, id))


@router.patch(
    "/admin/drug-food-interactions/{id}",
    response_model=DrugFoodInteraction,
    responses={**_ERRORS, **_NOT_FOUND, **_CONFLICT},
    operation_id="updateDrugFoodInteraction",
    summary="Admin: sửa quy tắc hoạt chất–thực phẩm (tạo phiên bản mới)",
)
def update_drug_food_interaction(
    id: int, payload: DrugFoodInteractionUpdate, uow: UowDep, admin: AdminDep
) -> DrugFoodInteraction:
    view = _food().update(uow, admin.id, id, payload.expected_version, payload.changes())
    return DrugFoodInteraction.from_view(view)


@router.delete(
    "/admin/drug-food-interactions/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={**_ERRORS, **_NOT_FOUND, **_CONFLICT},
    operation_id="deleteDrugFoodInteraction",
    summary="Admin: xóa mềm quy tắc hoạt chất–thực phẩm",
)
def delete_drug_food_interaction(
    id: int, expected_version: ExpectedVersion, uow: UowDep, admin: AdminDep
) -> Response:
    _food().delete(uow, admin.id, id, expected_version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/admin/drug-food-interactions/{id}/versions",
    response_model=DrugFoodInteractionVersionList,
    responses={**_ERRORS, **_NOT_FOUND},
    operation_id="listDrugFoodInteractionVersions",
    summary="Admin: lịch sử phiên bản của quy tắc hoạt chất–thực phẩm",
)
def list_drug_food_interaction_versions(
    id: int, uow: UowDep, _admin: AdminDep
) -> DrugFoodInteractionVersionList:
    return DrugFoodInteractionVersionList(
        items=[DrugFoodInteraction.from_view(v) for v in _food().history(uow, id)]
    )


@router.get(
    "/admin/drug-food-interaction-versions/{version_id}",
    response_model=DrugFoodInteraction,
    responses={
        **_ERRORS,
        404: {"model": ErrorDetail, "description": "`interaction_version_not_found`"},
    },
    operation_id="getDrugFoodInteractionVersion",
    summary="Admin: xem một phiên bản quy tắc hoạt chất–thực phẩm",
)
def get_drug_food_interaction_version(
    version_id: int, uow: UowDep, _admin: AdminDep
) -> DrugFoodInteraction:
    return DrugFoodInteraction.from_view(_food().get_version(uow, version_id))
