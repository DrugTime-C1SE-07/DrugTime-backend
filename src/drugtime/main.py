"""Composition root của Backend API (container Backend API)."""

from fastapi import FastAPI, Request
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
from drugtime.shared.errors import DomainError, Forbidden, NotFound, Unauthorized

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

_STATUS = {NotFound: 404, Unauthorized: 401, Forbidden: 403, DomainError: 422}


def create_app() -> FastAPI:
    app = FastAPI(title="DrugTime API", version="0.1.0")
    for module in MODULES:
        app.include_router(module.router)

    for exc_type, status in _STATUS.items():

        def handler(_: Request, exc: Exception, status: int = status) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=status)

        app.add_exception_handler(exc_type, handler)
    return app


app = create_app()
