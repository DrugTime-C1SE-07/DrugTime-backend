from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field

from drugtime.modules.catalog.domain.allergen import ALLERGENS
from drugtime.modules.identity import api as identity


class AllergenResponse(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    category: Literal["drug", "food"]
    name: str = Field(min_length=1)


class AllergensResponse(BaseModel):
    items: list[AllergenResponse]


class CatalogError(BaseModel):
    detail: str


class CatalogValidationError(BaseModel):
    detail: list[dict]


router = APIRouter(
    tags=["catalog"],
    dependencies=[
        Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
    ],
)


@router.get(
    "/allergens",
    operation_id="listAllergens",
    response_model=AllergensResponse,
    responses={
        401: {"model": CatalogError},
        422: {"model": CatalogValidationError},
        500: {"model": CatalogError},
    },
)
def list_allergens(request: Request, _user: identity.CurrentUser = Depends(identity.current_user)):
    if request.query_params:
        raise RequestValidationError(
            [
                {
                    "loc": ("query",),
                    "type": "extra_forbidden",
                    "msg": "Query parameters are not accepted",
                }
            ]
        )
    return {"items": ALLERGENS}
