"""Composition root của Backend API (container Backend API)."""

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from drugtime.modules.access import api as access
from drugtime.modules.adherence import api as adherence
from drugtime.modules.ai_meal import api as ai_meal
from drugtime.modules.catalog import api as catalog
from drugtime.modules.consent import api as consent
from drugtime.modules.family import api as family
from drugtime.modules.health import api as health
from drugtime.modules.identity import api as identity
from drugtime.modules.interaction import api as interaction
from drugtime.modules.medication import api as medication
from drugtime.shared.config import get_settings
from drugtime.shared.errors import (
    Conflict,
    DomainError,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
)

MODULES = [
    identity,
    consent,
    family,
    access,
    catalog,
    interaction,
    medication,
    adherence,
    ai_meal,
    health,
]

_STATUS = {
    NotFound: 404,
    Unauthorized: 401,
    Forbidden: 403,
    Conflict: 409,
    DomainError: 422,
    TooManyRequests: 429,
    ServiceUnavailable: 503,
}

_DELETION_ROUTES = frozenset({"/data-deletion-requests", "/data-deletion-requests/otp"})
_EMAIL_CHANGE_ROUTES = frozenset({
    "/me/email-change/otp", "/me/email-change/verify-current", "/me/email-change/confirm"
})


# Responses never cached; failures become the generic 500 without re-raising, so the
# server log never gets a traceback with sensitive SQL parameters (health data, OCR text).
_NO_STORE_ROUTES = frozenset(
    {
        ("GET", "/adherence"),
        ("POST", "/catalog/medications/match"),
        ("GET", "/family/patients"),
    }
)


def create_app() -> FastAPI:
    app = FastAPI(title="DrugTime API", version="0.1.0")
    origins = [o.strip() for o in get_settings().cors_allowed_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,  # xác thực bằng bearer, không dùng cookie
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )
    # medication đọc liều đã ghi qua port; adherence sở hữu dose_logs (task 2.04).
    medication.configure(recorded_doses=adherence.recorded_doses)
    for module in MODULES:
        app.include_router(module.router)

    for exc_type, status in _STATUS.items():

        def handler(_: Request, exc: Exception, status: int = status) -> JSONResponse:
            retry_after = getattr(exc, "retry_after", None)
            headers = None if retry_after is None else {"Retry-After": str(retry_after)}
            return JSONResponse({"detail": str(exc)}, status_code=status, headers=headers)

        app.add_exception_handler(exc_type, handler)

    def internal_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    app.add_exception_handler(Exception, internal_error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.scope["path"] not in (_DELETION_ROUTES | _EMAIL_CHANGE_ROUTES):
            return await request_validation_exception_handler(request, exc)
        # Pydantic validation details can echo the submitted OTP in input or context.
        errors = [
            {"loc": err["loc"], "msg": "Invalid input", "type": err["type"]}
            for err in exc.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.middleware("http")
    async def sensitive_no_store(request: Request, call_next):
        deletion = request.method == "POST" and request.scope["path"] in (
            _DELETION_ROUTES | _EMAIL_CHANGE_ROUTES
        )
        if not deletion and (request.method, request.url.path) not in _NO_STORE_ROUTES:
            return await call_next(request)
        try:
            response = await call_next(request)
        except Exception as exc:
            # Handle infrastructure/serialization failures here so ServerErrorMiddleware
            # never sends a health error without no-store or logs a sensitive exception.
            response = (
                JSONResponse({"detail": "service_unavailable"}, status_code=503)
                if deletion
                else internal_error(request, exc)
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


app = create_app()
