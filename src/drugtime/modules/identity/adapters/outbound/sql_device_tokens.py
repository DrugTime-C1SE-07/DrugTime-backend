from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from drugtime.shared.errors import Conflict


class SqlDeviceTokens:
    @staticmethod
    def _lock(uow, tokens):
        # Transaction advisory locks cover absent rows too. Stable order avoids deadlock.
        # hashtext collisions merely serialize unrelated tokens; no token is logged.
        for token in sorted(set(tokens)):
            uow.connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:t, 0))"), {"t": token}
            )

    def register(self, uow, user_id, token, previous):
        self._lock(uow, [token] + ([previous] if previous else []))
        try:
            # Savepoint giữ phần đăng ký và gỡ token cũ cùng thành công hoặc cùng rollback.
            with uow.connection.begin_nested():
                row = uow.connection.execute(
                    text("""
                    INSERT INTO device_tokens (user_id, fcm_token, platform)
                    VALUES (:u, :t, 'android')
                    ON CONFLICT (fcm_token) DO UPDATE
                    SET updated_at = now(), platform = EXCLUDED.platform
                    WHERE device_tokens.user_id = EXCLUDED.user_id
                    RETURNING user_id
                """),
                    {"u": user_id, "t": token},
                ).first()
                # UPSERT không đổi chủ sở hữu; token thuộc người khác không trả dòng nào.
                if row is None:
                    raise Conflict("device_token_in_use")
                if previous and previous != token:
                    self.unregister(uow, user_id, previous, locked=True)
        except IntegrityError as exc:
            raise Conflict("device_token_in_use") from exc

    def unregister(self, uow, user_id, token, *, locked=False):
        if not locked:
            self._lock(uow, [token])
        uow.connection.execute(
            text("DELETE FROM device_tokens WHERE user_id = :u AND fcm_token = :t"),
            {"u": user_id, "t": token},
        )
