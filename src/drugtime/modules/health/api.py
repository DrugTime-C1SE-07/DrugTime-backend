"""Giao diện công khai của health."""

from drugtime.modules.health.adapters.inbound.http import router
from drugtime.modules.health.adapters.outbound.probes import record_heartbeat

__all__ = ["record_heartbeat", "router"]
