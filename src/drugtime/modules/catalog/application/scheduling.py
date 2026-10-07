"""Pure scheduling policy for catalog synchronization."""

from datetime import datetime, timedelta

SYNC_INTERVAL = timedelta(days=7)


def is_sync_due(last_success_at: datetime | None, now: datetime) -> bool:
    """Return whether a source needs synchronization at ``now``."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if last_success_at is None:
        return True
    if last_success_at.tzinfo is None:
        raise ValueError("last_success_at must be timezone-aware")
    return now - last_success_at >= SYNC_INTERVAL
