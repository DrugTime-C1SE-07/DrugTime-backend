from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from drugtime.modules.catalog.adapters.inbound.schemas import (
    CatalogMedicationList,
    CatalogMedicationSummary,
    CatalogSyncRunList,
)
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.adapters.outbound.sql_sync_runs import SqlSyncRuns
from drugtime.modules.catalog.application.list_sync_runs import list_sync_runs
from drugtime.modules.catalog.application.search_medications import search_medications
from drugtime.modules.catalog.domain.sync_run import CatalogSyncSource, CatalogSyncStatus
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(tags=["catalog"])

# TODO: Admin: CRUD danh mục (xóa mềm), POST /admin/catalog/sync -> job_queue.enqueue_sync().


class ErrorDetail(BaseModel):
    detail: str


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
