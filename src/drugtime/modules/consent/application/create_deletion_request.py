from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime
from secrets import token_bytes
from uuid import UUID, uuid4

from drugtime.modules.consent.application.ports import DeletionCreationStore
from drugtime.modules.consent.domain.deletion_creation import (
    DELETION_DELAY,
    FAILURE_LIMIT,
    OTP_TTL,
    DeletionOtpInvalid,
    PendingDeletion,
)
from drugtime.modules.identity import api as identity
from drugtime.shared.errors import Conflict, ServiceUnavailable, TooManyRequests, Unauthorized
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class DeletionCreation:
    transactions: Callable[[], AbstractContextManager[UnitOfWork]]
    store: DeletionCreationStore
    verified_email: Callable[[UUID], str | None]
    send_otp: Callable[[str], None]
    verify_otp: Callable[[str, str], dict]
    clock: Callable[[], datetime]
    check_applying: Callable[[UnitOfWork, UUID], bool] = identity.email_change_applying

    def issue(self, user_id: UUID) -> tuple[UUID, datetime]:
        failure = None
        with self.transactions() as uow:
            self.store.lock(uow, user_id)
            if self.check_applying(uow, user_id):
                raise ServiceUnavailable("service_unavailable")
            state = self.store.otp_state(uow, user_id)
            at = self.clock()
            if state.failure_limit_reached(at):
                raise TooManyRequests("deletion_otp_rate_limited", state.retry_after(at))
            if state.send_limit_reached(at):
                raise TooManyRequests("deletion_otp_send_rate_limited", state.retry_after(at))
            state = state.reserve_send(at)
            challenge = uuid4()
            try:
                email = self.verified_email(user_id)
                if email is None:
                    raise Conflict("verified_email_required")
                self.send_otp(email)
            except (ServiceUnavailable, Conflict) as exc:
                failure = exc
            else:
                issued = self.clock()
                expires = issued + OTP_TTL
                state = replace(
                    state,
                    challenge_id=challenge,
                    # Supabase Auth owns the OTP. A random marker records only that
                    # this challenge was issued; it contains no code or verifier.
                    digest=token_bytes(32),
                    issued_at=issued,
                    expires_at=expires,
                    consumed_at=None,
                )
            self.store.save_otp(uow, user_id, state)
        if failure is not None:
            raise failure
        return challenge, expires

    def verify(self, user_id: UUID, challenge: UUID, otp: str) -> None:
        with self.transactions() as uow:
            self.store.lock(uow, user_id)
            if self.check_applying(uow, user_id):
                raise ServiceUnavailable("service_unavailable")
            state = self.store.otp_state(uow, user_id)
            at = self.clock()
            if state.failure_limit_reached(at):
                raise TooManyRequests("deletion_otp_rate_limited", state.retry_after(at))
            at = self.clock()
            if (
                state.challenge_id == challenge
                and state.consumed_at is not None
                and state.expires_at is not None
                and at < state.expires_at
            ):
                return  # provider verification succeeded before a lost response
            email = self.verified_email(user_id) if state.challenge_id == challenge else None
            if email and state.digest is not None and state.expires_at and at < state.expires_at:
                try:
                    verified = self.verify_otp(email, otp)
                    auth_user = verified.get("user") or {}
                    if UUID(str(auth_user.get("id"))) == user_id:
                        self.store.save_otp(uow, user_id, replace(state, consumed_at=at))
                        return
                except (Unauthorized, ValueError, TypeError, AttributeError):
                    pass
            failed = state.record_failure(at)
            self.store.save_otp(uow, user_id, failed)
        raise DeletionOtpInvalid(
            max(0, FAILURE_LIMIT - failed.failure_count),
            failed.retry_after(at) if failed.failure_limit_reached(at) else None,
        )

    def current(self, user_id: UUID) -> PendingDeletion | None:
        with self.transactions() as uow:
            self.store.lock(uow, user_id)
            return self.store.pending(uow, user_id)

    def cancel(self, user_id: UUID) -> None:
        with self.transactions() as uow:
            self.store.lock(uow, user_id)
            pending = self.store.pending(uow, user_id)
            if pending is None:
                if self.store.latest_completed(uow, user_id):
                    raise Conflict("deletion_request_due")
                return  # repeated cancellation after a lost ACK
            at = self.clock()
            if pending.scheduled_deletion_at is None:
                raise Conflict("deletion_request_not_cancellable")
            if pending.erasure_started_at is not None:
                raise Conflict("deletion_request_due")
            if at >= pending.scheduled_deletion_at:
                raise Conflict("deletion_request_due")
            self.store.cancel(uow, user_id, at)
            # A previously verified challenge must never recreate a request after
            # the user explicitly cancelled it.
            self.store.erase_otp(uow, user_id)

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

    def confirm(self, user_id: UUID, challenge: UUID) -> tuple[PendingDeletion, bool]:
        with self.transactions() as uow:
            self.store.lock(uow, user_id)
            state = self.store.otp_state(uow, user_id)
            at = self.clock()
            if (
                state.challenge_id != challenge
                or state.consumed_at is None
                or state.expires_at is None
                or at >= state.expires_at
            ):
                raise Conflict("deletion_otp_invalid")
            if self.check_applying(uow, user_id):
                raise ServiceUnavailable("service_unavailable")
            return self._record(uow, user_id, state, at)
