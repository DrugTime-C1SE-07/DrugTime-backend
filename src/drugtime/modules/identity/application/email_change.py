import hmac
from dataclasses import dataclass, replace
from datetime import datetime
from secrets import randbelow
from uuid import UUID, uuid4

from drugtime.modules.identity.domain.email_change import SEND_WINDOW, TTL, digest
from drugtime.modules.identity.domain.profile import validate_email
from drugtime.shared.errors import Conflict, DomainError, ServiceUnavailable, TooManyRequests


@dataclass(frozen=True)
class EmailChange:
    lock: object
    store: object
    auth: object
    send: object
    clock: object
    key: bytes

    def _ready(self, state, uid, conn):
        if len(self.key) < 32 or state.stage == "applying":
            raise ServiceUnavailable("service_unavailable")
        email = self.auth.verified_email(uid)
        profile = self.store.profile_email(conn, uid)
        if not email or not profile or email.strip().lower() != profile.strip().lower():
            raise Conflict("email_change_unavailable")
        return email.strip().lower()

    def _check(self, state, uid, challenge, otp, stage, now):
        if state.blocked(now):
            raise TooManyRequests("email_change_rate_limited")
        return bool(
            state.stage == stage
            and state.challenge_id == challenge
            and state.digest
            and state.expires_at
            and now < state.expires_at
            and hmac.compare_digest(
                state.digest,
                digest(self.key, uid, challenge, stage, state.old_email, state.new_email, otp),
            )
        )

    def start(self, uid: UUID, new_email: str) -> tuple[UUID, datetime]:
        target = validate_email(new_email)
        failure = None
        with self.lock(uid) as conn:
            with conn.begin():
                state = self.store.state(conn, uid)
                old = self._ready(state, uid, conn)
                now = self.clock()
                if state.blocked(now) or state.send_blocked(now):
                    raise TooManyRequests("email_change_rate_limited")
                if target == old or self.store.email_in_use(conn, uid, target):
                    raise Conflict("email_change_unavailable")
                reserved = state.reserve_send(now)
                challenge, otp = uuid4(), f"{randbelow(1_000_000):06d}"
                try:
                    self.send(old, otp)
                except ServiceUnavailable as exc:
                    failure = exc
                else:
                    now = self.clock()
                    reserved = replace(
                        reserved,
                        challenge_id=challenge,
                        old_email=old,
                        new_email=target,
                        stage="old",
                        digest=digest(self.key, uid, challenge, "old", old, target, otp),
                        issued_at=now,
                        expires_at=now + TTL,
                    )
                self.store.save(conn, uid, reserved)
        if failure:
            raise failure
        return challenge, reserved.expires_at

    def verify_current(self, uid: UUID, challenge: UUID, otp: str) -> tuple[UUID, datetime]:
        failure = None
        valid = False
        with self.lock(uid) as conn:
            with conn.begin():
                state = self.store.state(conn, uid)
                old = self._ready(state, uid, conn)
                now = self.clock()
                if not self._check(state, uid, challenge, otp, "old", now):
                    self.store.save(conn, uid, state.record_failure(now))
                elif state.old_email != old or self.store.email_in_use(conn, uid, state.new_email):
                    raise Conflict("email_change_unavailable")
                else:
                    if (
                        state.send_window_at
                        and now < state.send_window_at + SEND_WINDOW
                        and state.send_count >= 5
                    ):
                        raise TooManyRequests("email_change_rate_limited")
                    valid = True
                    state = state.reserve_send(now)
                    new_otp = f"{randbelow(1_000_000):06d}"
                    try:
                        self.send(state.new_email, new_otp)
                    except ServiceUnavailable as exc:
                        failure = exc
                    else:
                        now = self.clock()
                        state = replace(
                            state,
                            stage="new",
                            issued_at=now,
                            expires_at=now + TTL,
                            digest=digest(
                                self.key, uid, challenge, "new", old, state.new_email, new_otp
                            ),
                        )
                    self.store.save(conn, uid, state)
        if not valid:
            raise DomainError("email_change_otp_invalid")
        if failure:
            raise failure
        return challenge, state.expires_at

    def confirm(self, uid: UUID, challenge: UUID, otp: str) -> None:
        valid = False
        with self.lock(uid) as conn:
            with conn.begin():
                state = self.store.state(conn, uid)
                old = self._ready(state, uid, conn)
                now = self.clock()
                if not self._check(state, uid, challenge, otp, "new", now):
                    self.store.save(conn, uid, state.record_failure(now))
                elif state.old_email != old or self.store.email_in_use(conn, uid, state.new_email):
                    raise Conflict("email_change_unavailable")
                else:
                    valid = True
                    state = replace(state, stage="applying", digest=None)
                    self.store.save(conn, uid, state)
            if not valid:
                raise DomainError("email_change_otp_invalid")
            # Marker committed first: a crash or uncertain Auth result remains fail-closed.
            try:
                self.auth.update_email(uid, state.new_email)
                if self.auth.verified_email(uid) != state.new_email:
                    raise ServiceUnavailable("service_unavailable")
                with conn.begin():
                    self.store.finish(conn, uid, state)
                    self.store.save(conn, uid, replace(state, stage="done"))
            except Conflict:
                try:
                    # A definite conflict is safe to clear only if Auth and DB are still old.
                    if self.auth.verified_email(uid) != state.old_email:
                        raise ServiceUnavailable("service_unavailable")
                    with conn.begin():
                        if self.store.profile_email(conn, uid) != state.old_email:
                            raise ServiceUnavailable("service_unavailable")
                        self.store.save(conn, uid, replace(state, stage="done"))
                except Exception:
                    raise ServiceUnavailable("service_unavailable") from None
                raise Conflict("email_change_unavailable") from None
            except Exception:
                raise ServiceUnavailable("service_unavailable") from None

    def reconcile(self, uid: UUID) -> None:
        """Repair a durable applying marker. Caller must be trusted internal operations."""
        with self.lock(uid) as conn:
            with conn.begin():
                state = self.store.state(conn, uid)
                if state.stage != "applying":
                    return
                auth_email = self.auth.verified_email(uid)
                profile = self.store.profile_email(conn, uid)
                if auth_email == state.new_email and profile == state.old_email:
                    self.store.finish(conn, uid, state)
                elif auth_email == state.new_email and profile == state.new_email:
                    self.store.invalidate_deletion(conn, uid)
                elif auth_email != state.old_email or profile != state.old_email:
                    raise ServiceUnavailable("service_unavailable")
                self.store.save(conn, uid, replace(state, stage="done"))
