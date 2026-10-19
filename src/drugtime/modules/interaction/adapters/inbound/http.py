from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

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
)
from drugtime.modules.interaction.adapters.outbound.other_modules import (
    CatalogIngredients,
    IdentityAdmins,
)
from drugtime.modules.interaction.adapters.outbound.sql_interaction_rules import (
    SqlDrugFoodInteractions,
    SqlDrugInteractions,
)
from drugtime.modules.interaction.application.manage_drug_food_interactions import (
    drug_food_interaction_service,
)
from drugtime.modules.interaction.application.manage_drug_interactions import (
    drug_interaction_service,
)
from drugtime.modules.interaction.application.manage_rules import ListQuery
from drugtime.modules.interaction.domain.catalog_rules import InteractionType
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(tags=["interaction"])

# TODO: POST /patients/{id}/interaction-checks (DK3: access -> medication -> catalog -> evaluator)

UowDep = Annotated[SqlUnitOfWork, Depends(get_uow)]
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
