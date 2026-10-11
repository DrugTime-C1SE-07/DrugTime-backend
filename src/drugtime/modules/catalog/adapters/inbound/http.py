from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from drugtime.modules.catalog.adapters.inbound.schemas import (
    CatalogMedicationList,
    CatalogMedicationSummary,
    CatalogSyncRunList,
    MedicationCreate,
    MedicationListResponse,
    MedicationResponse,
    MedicationUpdate,
)
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.adapters.outbound.sql_sync_runs import SqlSyncRuns
from drugtime.modules.catalog.application.list_sync_runs import list_sync_runs
from drugtime.modules.catalog.application.search_medications import search_medications
from drugtime.modules.catalog.domain.sync_run import CatalogSyncSource, CatalogSyncStatus
from drugtime.modules.catalog.application.service import CatalogService
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(tags=["catalog"])

# TODO: Admin: CRUD danh mục (xóa mềm), POST /admin/catalog/sync -> job_queue.enqueue_sync().
UowDep = Annotated[SqlUnitOfWork, Depends(get_uow)]
AdminDep = Annotated[identity.CurrentUser, Depends(identity.require_admin)]
CurrentUserDep = Annotated[identity.CurrentUser, Depends(identity.current_user)]


class ErrorDetail(BaseModel):
    detail: str


# ============================================================================
# Mobile App / Tìm kiếm thuốc trong danh mục (K04)
# ============================================================================


@router.get(
    "/catalog/medications",
    response_model=CatalogMedicationList,
    responses={401: {"model": ErrorDetail, "description": "Chưa xác thực"}},
    operation_id="searchCatalogMedications",
)
def get_catalog_medications(
    q: str = Query(
        min_length=1,
        max_length=100,
        pattern=r"\S",
        description="Chuỗi tìm; phải có ít nhất một ký tự không phải khoảng trắng.",
    ),
    limit: int = Query(20, ge=1, le=50, description="Số kết quả tối đa."),
    uow: SqlUnitOfWork = Depends(get_uow),
    _user: identity.CurrentUser = Depends(identity.current_user),
) -> CatalogMedicationList:
    found = search_medications(uow, q, limit, SqlCatalog())
    return CatalogMedicationList(items=[CatalogMedicationSummary.from_domain(m) for m in found])


@router.get(
    "/admin/catalog/sync-runs",
    response_model=CatalogSyncRunList,
    responses={
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        403: {"model": ErrorDetail, "description": "Chỉ Admin"},
    },
    operation_id="listCatalogSyncRuns",
)
def get_catalog_sync_runs(
    source: Annotated[CatalogSyncSource | None, Query()] = None,
    status: Annotated[CatalogSyncStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    uow: SqlUnitOfWork = Depends(get_uow),
    _admin: identity.CurrentUser = Depends(identity.require_admin),
) -> CatalogSyncRunList:
    page = list_sync_runs(
        uow,
        SqlSyncRuns(),
        source=source,
        status=status,
        limit=limit,
        offset=offset,
    )
    return CatalogSyncRunList.from_domain(page)
# ============================================================================
# Admin Dashboard / CRUD danh mục thuốc (xóa mềm) (PB04, Task 2.13)
# ============================================================================


@router.post(
    "/admin/medications",
    response_model=MedicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: Thêm thuốc mới vào danh mục",
)
def create_medication(
    payload: MedicationCreate,
    uow: UowDep,
    _admin: AdminDep,
) -> MedicationResponse:
    return CatalogService(uow).create(payload)


@router.get(
    "/admin/medications",
    response_model=MedicationListResponse,
    summary="Admin: Danh sách thuốc phân trang, hỗ trợ tìm kiếm",
)
def list_medications_admin(
    uow: UowDep,
    _admin: AdminDep,
    q: Annotated[str | None, Query(max_length=100, description="Từ khóa tìm kiếm theo tên")] = None,
    skip: Annotated[int, Query(ge=0, description="Vị trí bắt đầu")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Số lượng bản ghi tối đa")] = 20,
) -> MedicationListResponse:
    items, total = CatalogService(uow).list(q=q, skip=skip, limit=limit)
    return MedicationListResponse(total=total, items=items)


@router.get(
    "/admin/medications/{med_id}",
    response_model=MedicationResponse,
    summary="Admin: Chi tiết một thuốc trong danh mục",
)
def get_medication_admin(
    med_id: int,
    uow: UowDep,
    _admin: AdminDep,
) -> MedicationResponse:
    return CatalogService(uow).get(med_id)


@router.patch(
    "/admin/medications/{med_id}",
    response_model=MedicationResponse,
    summary="Admin: Cập nhật thông tin thuốc",
)
def update_medication_admin(
    med_id: int,
    payload: MedicationUpdate,
    uow: UowDep,
    _admin: AdminDep,
) -> MedicationResponse:
    return CatalogService(uow).update(med_id, payload)


@router.delete(
    "/admin/medications/{med_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: Xóa mềm thuốc (đặt deleted_at)",
)
def delete_medication_admin(
    med_id: int,
    uow: UowDep,
    _admin: AdminDep,
) -> None:
    CatalogService(uow).soft_delete(med_id)
    return None
