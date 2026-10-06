from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from drugtime.modules.catalog.adapters.inbound.schemas import (
    CatalogMedicationList,
    CatalogMedicationSummary,
)
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.application.search_medications import search_medications
from drugtime.modules.identity import api as identity
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(tags=["catalog"])

# TODO: Admin: CRUD danh mục (xóa mềm), POST /admin/catalog/sync -> job_queue.enqueue_sync(),
#       GET /admin/catalog/sync-runs (task 2.13)


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
