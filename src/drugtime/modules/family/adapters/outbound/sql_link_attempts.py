"""Lượt nhập sai mã liên kết (task 3.13, QD-34 (c)). Không bao giờ nhận hay ghi mã đã thử."""

from datetime import datetime
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text

from drugtime.modules.family.domain.link_request import LinkRequestLimits
from drugtime.modules.family.domain.throttle import ThrottleState
from drugtime.shared.config import get_settings
from drugtime.shared.uow import UnitOfWork

# Chỉ quét dòng đủ mới để còn trong cửa sổ đếm hoặc còn mang khóa hiệu lực
# (index link_request_attempts_family_time_idx). client_uuid tra theo UNIQUE, không hết hạn.
_STATE = text("""
SELECT count(*) FILTER (WHERE attempted_at > :window_start) AS failures,
       max(account_locked_until) FILTER (WHERE account_locked_until > :now) AS locked_until,
       EXISTS (
           SELECT 1 FROM link_request_attempts
           WHERE family_user_id = :family_id AND client_uuid = :client_uuid
       ) AS client_uuid_failed
FROM link_request_attempts
WHERE family_user_id = :family_id AND attempted_at > :scan_from
""")

_INSERT = text("""
INSERT INTO link_request_attempts (family_user_id, client_uuid, attempted_at, account_locked_until)
VALUES (:family_id, :client_uuid, :attempted_at, :locked_until)
ON CONFLICT (family_user_id, client_uuid) DO NOTHING
""")


@lru_cache
def _failure_engine() -> Engine:
    """Pool riêng, nhỏ, chỉ để ghi lượt sai.

    Request đợi khóa người gửi vẫn giữ kết nối của pool chính. Nếu lượt sai cũng lấy từ pool
    chính, đủ nhiều request đồng thời của một người gửi sẽ chiếm hết pool: request giữ khóa không
    ghi được, chờ pool_timeout rồi lỗi, cả API treo theo (review 3.13, H1). Kết nối ở đây chỉ
    chạy một câu INSERT không chờ khóa nào, nên người giữ khóa luôn ghi xong rồi nhả khóa.
    """
    return create_engine(
        get_settings().database_url, pool_size=2, max_overflow=3, pool_pre_ping=True
    )


class SqlLinkAttempts:
    def state(
        self,
        uow: UnitOfWork,
        family_id: UUID,
        client_uuid: UUID,
        now: datetime,
        limits: LinkRequestLimits,
    ) -> ThrottleState:
        row = uow.connection.execute(
            _STATE,
            {
                "family_id": family_id,
                "client_uuid": client_uuid,
                "now": now,
                "window_start": now - limits.fail_window,
                "scan_from": now - max(limits.fail_window, limits.lock_duration),
            },
        ).one()
        return ThrottleState(
            failures_in_window=row.failures,
            locked_until=row.locked_until,
            client_uuid_failed=row.client_uuid_failed,
        )

    def record_failure(
        self,
        family_id: UUID,
        client_uuid: UUID,
        attempted_at: datetime,
        locked_until: datetime | None,
    ) -> None:
        # Transaction riêng: request trả 404 nên transaction của request sẽ rollback.
        with _failure_engine().begin() as conn:
            conn.execute(
                _INSERT,
                {
                    "family_id": family_id,
                    "client_uuid": client_uuid,
                    "attempted_at": attempted_at,
                    "locked_until": locked_until,
                },
            )
