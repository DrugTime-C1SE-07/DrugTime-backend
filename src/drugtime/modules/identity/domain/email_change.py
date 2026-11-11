import hmac
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

TTL = timedelta(minutes=5)
SEND_WINDOW = timedelta(hours=1)
FAILURE_WINDOW = timedelta(minutes=15)
COOLDOWN = timedelta(minutes=1)


@dataclass(frozen=True)
class EmailChangeState:
    challenge_id: UUID | None = None
    old_email: str | None = None
    new_email: str | None = None
    stage: str = "idle"
    digest: bytes | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    last_sent_at: datetime | None = None
    send_window_at: datetime | None = None
    send_count: int = 0
    failure_window_at: datetime | None = None
    failure_count: int = 0

    def reserve_send(self, now: datetime) -> "EmailChangeState":
        if self.send_window_at is None or now >= self.send_window_at + SEND_WINDOW:
            return replace(self, last_sent_at=now, send_window_at=now, send_count=1)
        return replace(self, last_sent_at=now, send_count=self.send_count + 1)

    def record_failure(self, now: datetime) -> "EmailChangeState":
        if self.failure_window_at is None or now >= self.failure_window_at + FAILURE_WINDOW:
            return replace(self, failure_window_at=now, failure_count=1)
        return replace(self, failure_count=self.failure_count + 1)

    def blocked(self, now: datetime) -> bool:
        return bool(
            self.failure_window_at
            and now < self.failure_window_at + FAILURE_WINDOW
            and self.failure_count >= 5
        )

    def send_blocked(self, now: datetime) -> bool:
        return bool(
            (self.last_sent_at and now < self.last_sent_at + COOLDOWN)
            or (
                self.send_window_at
                and now < self.send_window_at + SEND_WINDOW
                and self.send_count >= 5
            )
        )


def digest(
    key: bytes, uid: UUID, challenge: UUID, stage: str, old: str, new: str, otp: str
) -> bytes:
    message = f"email-change\0{uid}\0{challenge}\0{stage}\0{old}\0{new}\0{otp}"
    return hmac.digest(key, message.encode("utf8"), "sha256")
