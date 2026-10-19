import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from drugtime.modules.identity import api as identity
from drugtime.modules.medication.adapters.inbound.profile_schemas import (
    HealthProfileResponse,
    ProfileError,
    ProfileUpdateRequest,
    ProfileValidationError,
    UserConditionCreateRequest,
    UserConditionResponse,
    UserConditionUpdateRequest,
)
from drugtime.modules.medication.adapters.outbound.other_modules import (
    ConditionCatalogAdapter,
    HealthProfileAccessAdapter,
    IdentityProfileAdapter,
)
from drugtime.modules.medication.adapters.outbound.sql_user_conditions import SqlUserConditions
from drugtime.modules.medication.application.manage_profile import get_profile, update_profile
from drugtime.modules.medication.application.manage_user_conditions import (
    create_condition,
    delete_condition,
    update_condition,
)
from drugtime.modules.medication.domain.user_condition import NewUserCondition
from drugtime.shared.db import unit_of_work
from drugtime.shared.errors import DomainError, ServiceUnavailable

_LOGGER = logging.getLogger(__name__)

# Authentication remains in identity.current_user; this declares its bearer contract.
router = APIRouter(
    tags=["profile"],
    dependencies=[
        Depends(HTTPBearer(auto_error=False, scheme_name="bearerAuth", bearerFormat="JWT"))
    ],
)
_ACCESS = HealthProfileAccessAdapter()
_PROFILES = IdentityProfileAdapter()
_CONDITIONS = SqlUserConditions()
_CATALOG = ConditionCatalogAdapter()
_ERRORS = {code: {"model": ProfileError} for code in (401, 403, 500)}
_ERRORS[422] = {"model": ProfileValidationError}
_PROFILE_WRITE_ERRORS = {
    **_ERRORS,
    409: {"model": ProfileError},
    503: {"model": ProfileError},
}
_LINK_ERRORS = {**_ERRORS, 404: {"model": ProfileError}}
LinkId = Annotated[int, Path(ge=1, le=9223372036854775807, json_schema_extra={"format": "int64"})]
_NO_STORE = {"headers": {"Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}}


def _self_only(request: Request) -> None:
    if {"user_id", "patient_id"} & request.query_params.keys():
        raise DomainError("profile_is_self_only")


def _json(model: HealthProfileResponse | UserConditionResponse, status: int = 200):
    return JSONResponse(
        model.model_dump(mode="json"), status_code=status, headers={"Cache-Control": "no-store"}
    )


@router.get(
    "/profile",
    response_model=HealthProfileResponse,
    responses={**_ERRORS, 200: _NO_STORE},
    operation_id="getOwnHealthProfile",
)
def read_profile(request: Request, user: identity.CurrentUser = Depends(identity.current_user)):
    _self_only(request)
    with unit_of_work() as uow:
        result = get_profile(
            uow,
            user_id=user.id,
            is_admin=user.is_admin,
            access=_ACCESS,
            profiles=_PROFILES,
            conditions=_CONDITIONS,
            catalog=_CATALOG,
        )
        response = _json(HealthProfileResponse.model_validate(result))
    return response


@router.put(
    "/profile",
    status_code=204,
    responses=_PROFILE_WRITE_ERRORS,
    operation_id="updateOwnProfile",
)
def put_profile(
    body: ProfileUpdateRequest,
    request: Request,
    user: identity.CurrentUser = Depends(identity.current_user),
):
    _self_only(request)
    change = None
    try:
        with unit_of_work() as uow:
            change = update_profile(
                uow,
                user_id=user.id,
                is_admin=user.is_admin,
                access=_ACCESS,
                profiles=_PROFILES,
                full_name=body.full_name,
                date_of_birth=body.date_of_birth,
                gender=body.gender,
                email=body.email,
                at=datetime.now(UTC),
            )
            response = Response(status_code=204)
    except Exception:
        if change is not None and change[1]:
            try:
                identity.restore_profile_email(user.id, change[0])
            except Exception as rollback_error:
                _LOGGER.error(
                    "Could not restore Auth email after profile transaction failure for user %s",
                    user.id,
                )
                raise ServiceUnavailable("auth_provider_unavailable") from rollback_error
        raise
    return response


@router.post(
    "/profile/conditions",
    status_code=201,
    response_model=UserConditionResponse,
    responses={**_ERRORS, 201: _NO_STORE, 409: {"model": ProfileError}},
    operation_id="createOwnCondition",
)
def post_condition(
    body: UserConditionCreateRequest,
    request: Request,
    user: identity.CurrentUser = Depends(identity.current_user),
):
    _self_only(request)
    with unit_of_work() as uow:
        result = create_condition(
            uow,
            user_id=user.id,
            is_admin=user.is_admin,
            access=_ACCESS,
            conditions=_CONDITIONS,
            catalog=_CATALOG,
            cmd=NewUserCondition(**body.model_dump()),
        )
        response = _json(UserConditionResponse.model_validate(result), 201)
    return response


@router.patch(
    "/profile/conditions/{id}",
    response_model=UserConditionResponse,
    responses={**_LINK_ERRORS, 200: _NO_STORE},
    operation_id="updateOwnCondition",
)
def patch_condition(
    id: LinkId,
    body: UserConditionUpdateRequest,
    request: Request,
    user: identity.CurrentUser = Depends(identity.current_user),
):
    _self_only(request)
    with unit_of_work() as uow:
        result = update_condition(
            uow,
            user_id=user.id,
            is_admin=user.is_admin,
            access=_ACCESS,
            conditions=_CONDITIONS,
            catalog=_CATALOG,
            link_id=id,
            fields=body.model_dump(exclude_unset=True),
        )
        response = _json(UserConditionResponse.model_validate(result))
    return response


@router.delete(
    "/profile/conditions/{id}",
    status_code=204,
    responses=_LINK_ERRORS,
    operation_id="deleteOwnCondition",
)
def remove_condition(
    id: LinkId, request: Request, user: identity.CurrentUser = Depends(identity.current_user)
):
    _self_only(request)
    with unit_of_work() as uow:
        delete_condition(
            uow,
            user_id=user.id,
            is_admin=user.is_admin,
            access=_ACCESS,
            conditions=_CONDITIONS,
            link_id=id,
        )
        response = Response(status_code=204)
    return response
