from contextlib import contextmanager
from dataclasses import asdict, fields
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from drugtime.modules.identity.domain.email_change import EmailChangeState
from drugtime.shared.db import SqlUnitOfWork, get_engine
from drugtime.shared.errors import Conflict, ServiceUnavailable

_COLS = tuple(field.name for field in fields(EmailChangeState))
_NAMES = ", ".join(_COLS)
_VALUES = ", ".join(f":{name}" for name in _COLS)
_UPDATES = ", ".join(f"{name}=EXCLUDED.{name}" for name in _COLS)


@contextmanager
def account_lock(uid: UUID):
    with get_engine().connect() as conn:
        locked = False
        try:
            conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            conn.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:key,0))"),
                {"key": f"account-deletion:{uid}"},
            )
            locked = True
            conn.commit()
            yield conn
        finally:
            if locked:
                try:
                    if conn.in_transaction():
                        conn.rollback()
                    released = conn.execute(
                        text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                        {"key": f"account-deletion:{uid}"},
                    ).scalar_one()
                    conn.commit()
                    if not released:
                        raise ServiceUnavailable("service_unavailable")
                except Exception:
                    conn.invalidate()
                    raise
            elif conn.in_transaction():
                try:
                    conn.rollback()
                except Exception:
                    conn.invalidate()
                    raise


class SqlEmailChange:
    def state(self, conn, uid: UUID) -> EmailChangeState:
        row = (
            conn.execute(
                text(f"SELECT {_NAMES} FROM email_change_challenges WHERE user_id=:uid"),
                {"uid": uid},
            )
            .mappings()
            .one_or_none()
        )
        return EmailChangeState(**row) if row else EmailChangeState()

    def save(self, conn, uid: UUID, state: EmailChangeState) -> None:
        conn.execute(
            text(
                f"INSERT INTO email_change_challenges (user_id,{_NAMES}) VALUES (:uid,{_VALUES}) "
                f"ON CONFLICT (user_id) DO UPDATE SET {_UPDATES}"
            ),
            {"uid": uid, **asdict(state)},
        )

    def profile_email(self, conn, uid: UUID) -> str | None:
        return conn.execute(
            text("SELECT email FROM users WHERE id=:uid AND erased_at IS NULL"), {"uid": uid}
        ).scalar_one_or_none()

    def email_in_use(self, conn, uid: UUID, email: str) -> bool:
        return bool(
            conn.execute(
                text("SELECT EXISTS(SELECT 1 FROM users WHERE lower(email)=:email AND id<>:uid)"),
                {"email": email, "uid": uid},
            ).scalar_one()
        )

    def finish(self, conn, uid: UUID, state: EmailChangeState) -> None:
        try:
            result = conn.execute(
                text(
                    "UPDATE users SET email=:new WHERE id=:uid AND lower(email)=:old "
                    "AND erased_at IS NULL"
                ),
                {"new": state.new_email, "old": state.old_email, "uid": uid},
            )
        except IntegrityError:
            raise Conflict("email_change_unavailable") from None
        if result.rowcount != 1:
            raise ServiceUnavailable("service_unavailable")
        self.invalidate_deletion(conn, uid)

    def invalidate_deletion(self, conn, uid: UUID) -> None:
        conn.execute(
            text(
                "UPDATE deletion_otp_challenges SET challenge_id=NULL, digest=NULL, "
                "issued_at=NULL, expires_at=NULL, consumed_at=NULL WHERE user_id=:uid"
            ),
            {"uid": uid},
        )

    def applying(self, uow: SqlUnitOfWork, uid: UUID) -> bool:
        return bool(
            uow.connection.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM email_change_challenges "
                    "WHERE user_id=:uid AND stage='applying')"
                ),
                {"uid": uid},
            ).scalar_one()
        )
