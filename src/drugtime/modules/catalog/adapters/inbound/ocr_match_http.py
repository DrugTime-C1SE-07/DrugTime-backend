"""POST /catalog/medications/match: suggest catalog medications from OCR text (PB31, 4.13).

Catalog data is shared, not one patient's health data: any valid session may call it,
no PEP, no access log (QD-44). The request body is never logged (QD-39, QD-33);
`main.py` adds `Cache-Control: no-store` to every response of this route.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from drugtime.modules.catalog.adapters.inbound.http import ErrorDetail
from drugtime.modules.catalog.adapters.inbound.ocr_match_schemas import (
    OcrMatchRequest,
    OcrMatchResult,
)
from drugtime.modules.catalog.adapters.outbound.sql_catalog import SqlCatalog
from drugtime.modules.catalog.application.match_ocr_text import match_ocr_text
from drugtime.modules.catalog.domain.ocr_match import MatchPolicy
from drugtime.modules.identity import api as identity
from drugtime.shared.config import get_settings
from drugtime.shared.db import SqlUnitOfWork, get_uow

router = APIRouter(
    tags=["catalog"],
    dependencies=[
        Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
    ],
)

_NO_STORE = {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}


@router.post(
    "/catalog/medications/match",
    response_model=OcrMatchResult,
    responses={
        200: {"headers": _NO_STORE},
        401: {"model": ErrorDetail, "description": "Chưa xác thực"},
        422: {"headers": _NO_STORE},
        500: {"model": ErrorDetail, "description": "Lỗi nội bộ", "headers": _NO_STORE},
    },
    operation_id="matchCatalogMedicationsFromOcr",
)
def match_medications(
    body: OcrMatchRequest,
    uow: SqlUnitOfWork = Depends(get_uow),
    _user: identity.CurrentUser = Depends(identity.current_user),
) -> JSONResponse:
    outcome = match_ocr_text(
        uow,
        body.text,
        limit=body.limit,
        policy=MatchPolicy.from_settings(get_settings()),
        reader=SqlCatalog(),
    )
    payload = OcrMatchResult.from_domain(outcome).model_dump(mode="json")
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
