from datetime import datetime, timedelta

from drugtime.modules.health.application.ports import Probes
from drugtime.modules.health.domain.readiness import heartbeat_fresh


def readiness(probes: Probes, now: datetime, max_heartbeat_age: timedelta) -> dict[str, bool]:
    db = probes.database_ok()
    return {
        "database": db,
        "redis": probes.redis_ok(),
        "worker_heartbeat": db and heartbeat_fresh(probes.last_heartbeat(), now, max_heartbeat_age),
    }
