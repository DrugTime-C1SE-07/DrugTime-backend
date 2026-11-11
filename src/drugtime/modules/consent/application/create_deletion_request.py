from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime
from secrets import randbelow
from uuid import UUID, uuid4

from drugtime.modules.consent.application.ports import DeletionCreationStore
from drugtime.modules.consent.domain.deletion_creation import (
    DELETION_DELAY,
    OTP_TTL,
    PendingDeletion,
    otp_digest,
)
from drugtime.modules.identity import api as identity
from drugtime.shared.errors import Conflict, DomainError, ServiceUnavailable, TooManyRequests
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class DeletionCreation:
    transactions: Callable[[], AbstractContextManager[UnitOfWork]]
    store: DeletionCreationStore
    verified_email: Callable[[UUID], str | None]
    send_otp: Callable[[str, str], None]
    clock: Callable[[], datetime]
    key: bytes
    check_applying: Callable[[UnitOfWork, UUID], bool] = identity.email_change_applying

    def issue(self, user_id: UUID) -> tuple[UUID, datetime]:
        self._check_key()
        failure = None
        with self.transactions() as uow:
            self.store.lock(uow, user_id)
            if self.check_applying(uow, user_id):
                raise ServiceUnavailable("service_unavailable")
            state = self.store.otp_state(uow, user_id)
            at = self.clock()
            if state.send_limit_reached(at) or state.failure_limit_reached(at):
                raise TooManyRequests("deletion_otp_rate_limited")
            state = state.reserve_send(at)
            challenge = uuid4()
            otp = f"{randbelow(1_000_000):06d}"
            try:
                email = self.verified_email(user_id)
                if email is None:
                    raise Conflict("verified_email_required")
                self.send_otp(email, otp)
            except (ServiceUnavailable, Conflict) as exc:
                failure = exc
            else:
                issued = self.clock()
                expires = issued + OTP_TTL
                state = replace(
                    state,
                    challenge_id=challenge,
                    digest=otp_digest(self.key, user_id, challenge, email, otp),
                    issued_at=issued,
                    expires_at=expires,
                    consumed_at=None,
                )
            self.store.save_otp(uow, user_id, state)
        if failure is not None:
            raise failure
        return challenge, expires

    def confirm(
        self, user_id: UUID, challenge: UUID, otp: str
    ) -> tuple[PendingDeletion, bool]:
        self._check_key()
        with self.transactions() as uow:
            self.store.lock(uow, user_id)
            if self.check_applying(uow, user_id):
                raise ServiceUnavailable("service_unavailable")
            state = self.store.otp_state(uow, user_id)
            at = self.clock()
            if state.failure_limit_reached(at):
                raise TooManyRequests("deletion_otp_rate_limited")
            email = self.verified_email(user_id) if state.challenge_id == challenge else None
            at = self.clock()
            if email and state.accepts(
                challenge, otp_digest(self.key, user_id, challenge, email, otp), at
            ):
                return self._record(uow, user_id, state, at)
            self.store.save_otp(uow, user_id, state.record_failure(at))
        raise DomainError("deletion_otp_invalid")

    def _record(self, uow, user_id, state, at) -> tuple[PendingDeletion, bool]:
        existing = self.store.pending(uow, user_id)
        if existing is not None:
            if existing.scheduled_deletion_at is None:
                raise ServiceUnavailable("service_unavailable")
            if at >= existing.scheduled_deletion_at:
                raise Conflict("deletion_request_due")
        result = existing or PendingDeletion(at, at + DELETION_DELAY)
        if existing is None:
            self.store.insert(uow, user_id, result)
        self.store.save_otp(uow, user_id, replace(state, consumed_at=at))
        return result, existing is None

    def _check_key(self) -> None:
        if len(self.key) < 32:
            raise ServiceUnavailable("service_unavailable")
