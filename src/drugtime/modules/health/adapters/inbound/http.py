from datetime import timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from drugtime.modules.health.adapters.outbound.probes import LiveProbes
from drugtime.modules.health.application.check import readiness
from drugtime.shared.clock import now
from drugtime.shared.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    """Liveness: tiến trình còn phục vụ được request."""
    return {"status": "ok"}


@router.get("/ready")
def ready() -> JSONResponse:
    """Readiness (CD4): database, Redis, heartbeat Worker."""
    result = readiness(
        LiveProbes(), now(), timedelta(seconds=get_settings().heartbeat_max_age_seconds)
    )
    return JSONResponse(result, status_code=200 if all(result.values()) else 503)
