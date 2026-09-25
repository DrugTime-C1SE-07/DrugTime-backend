from datetime import datetime, timedelta


def heartbeat_fresh(last_beat_at: datetime | None, now: datetime, max_age: timedelta) -> bool:
    return last_beat_at is not None and now - last_beat_at <= max_age
