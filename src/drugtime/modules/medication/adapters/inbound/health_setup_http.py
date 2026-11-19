from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import ValidationError

from drugtime.modules.identity import api as identity
from drugtime.modules.medication.adapters.inbound.health_setup_schemas import (
    HealthSetupRequest,
    HealthSetupResponse,
    decode_step,
)
from drugtime.modules.medication.adapters.inbound.profile_schemas import (
    ProfileError,
    ProfileValidationError,
)
from drugtime.modules.medication.adapters.outbound.other_modules import (
    ConditionCatalogAdapter,
    HealthProfileAccessAdapter,
)
from drugtime.modules.medication.adapters.outbound.sql_health_setup import SqlHealthSetup
from drugtime.modules.medication.adapters.outbound.sql_user_conditions import SqlUserConditions
from drugtime.modules.medication.application.manage_health_setup import read_setup, save_setup
from drugtime.shared.db import unit_of_work

router = APIRouter(
    tags=["profile"],
    dependencies=[
        Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
    ],
)
_ACCESS = HealthProfileAccessAdapter()
_STORE = SqlHealthSetup()
_LINKS = SqlUserConditions()
_CATALOG = ConditionCatalogAdapter()
_ERRORS = {code: {"model": ProfileError} for code in (401, 403, 500)}
_ERRORS[422] = {"model": ProfileValidationError}
_NO_STORE = {"headers": {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}}
_HEALTH_ROUTE = {"x-health-scope": "ho_so_suc_khoe", "x-health-audit-self": True}

# The response registers the same step schemas in OpenAPI components.
_UPDATE_SCHEMA = HealthSetupRequest.model_json_schema(ref_template="#/components/schemas/{model}")
_UPDATE_SCHEMA.pop("$defs")


def _other_owner(value: str, owner: UUID) -> bool:
    try:
        return UUID(value) != owner
    except ValueError:
        return True


def _target_id(value: str | None, owner: UUID) -> UUID:
    if value is not None:
        try:
            return UUID(value)
        except ValueError:
            return owner
    return owner


def _authorize(uow, request: Request, user: identity.CurrentUser, *, writes: bool) -> None:
    selectors = request.query_params.multi_items()
    other_owner = next(
        (
            value
            for name, value in selectors
            if name in {"user_id", "patient_id"} and _other_owner(value, user.id)
        ),
        None,
    )
    _ACCESS.authorize_setup(
        uow,
        user.id,
        user.is_admin,
        writes=writes,
        rejected_owner_selector=other_owner is not None,
        target_id=_target_id(other_owner, user.id),
    )
    if selectors:
        raise RequestValidationError(
            [
                {
                    "loc": ("query",),
                    "type": "extra_forbidden",
                    "msg": "Query parameters are not accepted",
                }
            ]
        )


def _response(snapshot):
    body = HealthSetupResponse.from_setup(snapshot).model_dump(mode="json")
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get(
    "/profile/health-setup",
    operation_id="getOwnHealthSetup",
    response_model=HealthSetupResponse,
    responses={**_ERRORS, 200: _NO_STORE},
    openapi_extra=_HEALTH_ROUTE,
)
def get_health_setup(request: Request, user: identity.CurrentUser = Depends(identity.current_user)):
    with unit_of_work() as uow:
        _authorize(uow, request, user, writes=False)
        return _response(read_setup(uow, user.id, _STORE, _LINKS))


@router.put(
    "/profile/health-setup",
    operation_id="replaceOwnHealthSetupSteps",
    response_model=HealthSetupResponse,
    responses={**_ERRORS, 200: _NO_STORE, 409: {"model": ProfileError}},
    openapi_extra={
        **_HEALTH_ROUTE,
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _UPDATE_SCHEMA}},
        },
    },
)
async def put_health_setup(
    request: Request,
    user: identity.CurrentUser = Depends(identity.current_user),
):
    raw_body = await request.body()
    return await run_in_threadpool(_authorize_and_save, request, user, raw_body)


def _authorize_and_save(request: Request, user: identity.CurrentUser, raw_body: bytes):
    # Parse and validate only after authorization, in the same transaction as the write.
    with unit_of_work() as uow:
        _authorize(uow, request, user, writes=True)
        try:
            body = HealthSetupRequest.model_validate_json(raw_body)
        except ValidationError as exc:
            raise RequestValidationError(
                [
                    {**error, "loc": ("body", *error["loc"])}
                    for error in exc.errors(
                        include_input=False, include_context=False, include_url=False
                    )
                ]
            ) from None
        return _response(
            save_setup(
                uow,
                user.id,
                _STORE,
                _LINKS,
                _CATALOG,
                _CATALOG.allergen_exists,
                body.revision,
                decode_step(body.allergies),
                decode_step(body.conditions),
            )
        )
