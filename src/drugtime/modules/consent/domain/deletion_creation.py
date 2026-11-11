import hmac
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

OTP_TTL = timedelta(minutes=5)
SEND_COOLDOWN = timedelta(seconds=60)
SEND_WINDOW = timedelta(hours=1)
FAILURE_WINDOW = timedelta(minutes=15)
SEND_LIMIT = 5
FAILURE_LIMIT = 5
DELETION_DELAY = timedelta(hours=720)


@dataclass(frozen=True)
class DeletionOtpState:
    challenge_id: UUID | None = None
    digest: bytes | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    consumed_at: datetime | None = None
    last_sent_at: datetime | None = None
    send_window_at: datetime | None = None
    send_count: int = 0
    failure_window_at: datetime | None = None
    failure_count: int = 0

    def reserve_send(self, at: datetime) -> "DeletionOtpState":
        start = self.send_window_at
        if start is None or at >= start + SEND_WINDOW:
            return replace(self, last_sent_at=at, send_window_at=at, send_count=1)
        return replace(self, last_sent_at=at, send_count=self.send_count + 1)

    def record_failure(self, at: datetime) -> "DeletionOtpState":
        start = self.failure_window_at
        if start is None or at >= start + FAILURE_WINDOW:
            return replace(self, failure_window_at=at, failure_count=1)
        return replace(self, failure_count=self.failure_count + 1)

    def failure_limit_reached(self, at: datetime) -> bool:
        return (
            self.failure_window_at is not None
            and at < self.failure_window_at + FAILURE_WINDOW
            and self.failure_count >= FAILURE_LIMIT
        )

    def send_limit_reached(self, at: datetime) -> bool:
        if self.last_sent_at is not None and at < self.last_sent_at + SEND_COOLDOWN:
            return True
        return (
            self.send_window_at is not None
            and at < self.send_window_at + SEND_WINDOW
            and self.send_count >= SEND_LIMIT
        )

    def accepts(self, challenge_id: UUID, digest: bytes, at: datetime) -> bool:
        return (
            self.challenge_id == challenge_id
            and self.digest is not None
            and self.expires_at is not None
            and at < self.expires_at
            and self.consumed_at is None
            and hmac.compare_digest(self.digest, digest)
        )


@dataclass(frozen=True)
class PendingDeletion:
    requested_at: datetime
    scheduled_deletion_at: datetime | None


def otp_digest(key: bytes, user_id: UUID, challenge: UUID, email: str, otp: str) -> bytes:
    message = f"account-deletion\0{user_id}\0{challenge}\0{email}\0{otp}"
    return hmac.digest(key, message.encode(), "sha256")
