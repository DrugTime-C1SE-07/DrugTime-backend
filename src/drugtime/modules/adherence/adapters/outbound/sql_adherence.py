from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from drugtime.modules.adherence.domain.alert import NotificationRecord
from drugtime.modules.adherence.domain.dose import (
    ClientUuidConflict,
    DoseConfirmation,
    DoseConfirmationPersistenceResult,
    DoseLogRecord,
    DoseStatus,
)
from drugtime.shared.uow import UnitOfWork

_SELECT_BY_CLIENT_UUID = text("""
SELECT id, medication_schedule_id, scheduled_at, taken_at, status, client_uuid, synced_at
FROM dose_logs
WHERE client_uuid = :client_uuid
""")

# Cài đúng domain.dose.status_for_confirmation: quá +120 phút lưu bo_lo, không ghi taken_at.
_UPSERT_CONFIRMATION = text("""
INSERT INTO dose_logs (medication_schedule_id, scheduled_at, taken_at, status, client_uuid,
                       synced_at)
VALUES (:schedule_id, :scheduled_at, :taken_at, :status, :client_uuid, now())
ON CONFLICT (medication_schedule_id, scheduled_at) DO UPDATE SET
    status = CASE WHEN dose_logs.status = 'bo_lo' AND EXCLUDED.status <> 'bo_lo'
                  THEN 'uong_tre' ELSE dose_logs.status END,
    taken_at = CASE WHEN dose_logs.status = 'bo_lo' AND EXCLUDED.status <> 'bo_lo'
                    THEN EXCLUDED.taken_at
                    ELSE dose_logs.taken_at END,
    client_uuid = CASE WHEN dose_logs.status = 'bo_lo' AND dose_logs.client_uuid IS NULL
                       THEN EXCLUDED.client_uuid ELSE dose_logs.client_uuid END,
    synced_at = CASE WHEN dose_logs.status = 'bo_lo' THEN now() ELSE dose_logs.synced_at END
RETURNING id, medication_schedule_id, scheduled_at, taken_at, status, client_uuid, synced_at
""")

# Cài đúng domain.dose.may_mark_missed: chỉ tạo khi chưa có dòng.
_MARK_MISSED = text("""
INSERT INTO dose_logs (medication_schedule_id, scheduled_at, status)
VALUES (:schedule_id, :scheduled_at, 'bo_lo')
ON CONFLICT (medication_schedule_id, scheduled_at) DO NOTHING
RETURNING id
""")


class SqlDoseLogs:
    def upsert_confirmation(
        self, uow: UnitOfWork, c: DoseConfirmation, status: DoseStatus
    ) -> DoseConfirmationPersistenceResult:
        existing = uow.connection.execute(
            _SELECT_BY_CLIENT_UUID,
            {"client_uuid": c.client_uuid},
        ).first()
        if existing is not None:
            record = _record(existing)
            if (
                record.schedule_id != c.schedule_id
                or record.scheduled_at != c.scheduled_at
                or (record.status is not DoseStatus.MISSED and record.taken_at != c.taken_at)
            ):
                raise ClientUuidConflict()
            return DoseConfirmationPersistenceResult(
                record=record,
                adherence_counted=record.status is not DoseStatus.MISSED,
            )

        row = uow.connection.execute(
            _UPSERT_CONFIRMATION,
            {
                "schedule_id": c.schedule_id,
                "scheduled_at": c.scheduled_at,
                "taken_at": None if status is DoseStatus.MISSED else c.taken_at,
                "client_uuid": c.client_uuid,
                "status": status.value,
            },
        ).one()
        record = _record(row)
        return DoseConfirmationPersistenceResult(
            record=record,
            adherence_counted=record.status is not DoseStatus.MISSED,
        )

    def mark_missed(self, uow: UnitOfWork, schedule_id: int, scheduled_at: datetime) -> int | None:
        row = uow.connection.execute(
            _MARK_MISSED, {"schedule_id": schedule_id, "scheduled_at": scheduled_at}
        ).first()
        return None if row is None else row.id

    def latest_at_or_after(
        self, uow: UnitOfWork, schedule_ids: list[int], at: datetime
    ) -> dict[int, datetime]:
        """Giờ dự kiến muộn nhất của liều đã ghi với giờ dự kiến >= at, theo lịch (cho medication
        tính mốc hiệu lực khi sửa lịch, task 2.04)."""
        if not schedule_ids:
            return {}
        rows = uow.connection.execute(
            text(
                "SELECT medication_schedule_id, max(scheduled_at) AS latest FROM dose_logs "
                "WHERE medication_schedule_id = ANY(:ids) AND scheduled_at >= :at "
                "GROUP BY medication_schedule_id"
            ),
            {"ids": list(schedule_ids), "at": at},
        )
        return {r.medication_schedule_id: r.latest for r in rows}

    def erase_for_schedules(self, uow: UnitOfWork, schedule_ids: list[int]) -> None:
        if schedule_ids:
            uow.connection.execute(
                text("DELETE FROM dose_logs WHERE medication_schedule_id = ANY(:ids)"),
                {"ids": schedule_ids},
            )


class SqlNotifications:
    def create_missed_alert(
        self,
        uow: UnitOfWork,
        recipient_id: UUID,
        patient_id: UUID,
        dedupe_key: str,
        content: str | None = None,
    ) -> int | None:
        row = uow.connection.execute(
            text("""
            INSERT INTO notifications (user_id, about_patient_user_id, type, content, is_read,
                                       dedupe_key)
            VALUES (:r, :p, 'canh_bao_bo_lo_lieu_nguoi_than', :content, false, :k)
            ON CONFLICT (dedupe_key) DO NOTHING
            RETURNING id
        """),
            {
                "r": recipient_id,
                "p": patient_id,
                "k": dedupe_key,
                "content": content or "Chưa ghi nhận liều thuốc đúng giờ",
            },
        ).first()
        return None if row is None else row.id

    def list_for_user(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        is_read: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationRecord], int, int]:
        # 1. Total matching filter
        if is_read is None:
            r_tot = uow.connection.execute(
                text("SELECT count(*) AS total FROM notifications WHERE user_id = :u"),
                {"u": user_id},
            ).first()
        else:
            r_tot = uow.connection.execute(
                text("SELECT count(*) AS total FROM notifications WHERE user_id = :u AND is_read = :ir"),
                {"u": user_id, "ir": is_read},
            ).first()
        total = int(getattr(r_tot, "total", None) if hasattr(r_tot, "total") else (r_tot[0] if r_tot else 0))

        # 2. Unread count
        r_un = uow.connection.execute(
            text("SELECT count(*) AS unread FROM notifications WHERE user_id = :u AND is_read = false"),
            {"u": user_id},
        ).first()
        unread = int(getattr(r_un, "unread", None) if hasattr(r_un, "unread") else (r_un[0] if r_un else 0))

        # 3. Items
        if is_read is None:
            query = text("""
                SELECT n.id, n.user_id, n.about_patient_user_id, n.type, n.content, n.is_read, n.created_at,
                       u.full_name AS about_patient_name
                FROM notifications n
                LEFT JOIN users u ON u.id = n.about_patient_user_id
                WHERE n.user_id = :u
                ORDER BY n.created_at DESC, n.id DESC
                LIMIT :limit OFFSET :offset
            """)
            rows = uow.connection.execute(
                query,
                {"u": user_id, "limit": limit, "offset": offset},
            )
        else:
            query = text("""
                SELECT n.id, n.user_id, n.about_patient_user_id, n.type, n.content, n.is_read, n.created_at,
                       u.full_name AS about_patient_name
                FROM notifications n
                LEFT JOIN users u ON u.id = n.about_patient_user_id
                WHERE n.user_id = :u AND n.is_read = :ir
                ORDER BY n.created_at DESC, n.id DESC
                LIMIT :limit OFFSET :offset
            """)
            rows = uow.connection.execute(
                query,
                {"u": user_id, "ir": is_read, "limit": limit, "offset": offset},
            )

        items = [
            NotificationRecord(
                id=r.id,
                user_id=r.user_id,
                about_patient_user_id=r.about_patient_user_id,
                type=r.type,
                content=r.content,
                is_read=r.is_read,
                created_at=r.created_at,
                about_patient_name=getattr(r, "about_patient_name", None),
            )
            for r in (rows or [])
        ]
        return items, total, unread

    def mark_as_read(
        self,
        uow: UnitOfWork,
        notification_id: int,
        user_id: UUID,
        is_read: bool = True,
    ) -> NotificationRecord | None:
        row = uow.connection.execute(
            text("""
                UPDATE notifications
                SET is_read = :ir
                WHERE id = :id AND user_id = :u
                RETURNING id, user_id, about_patient_user_id, type, content, is_read, created_at
            """),
            {"id": notification_id, "u": user_id, "ir": is_read},
        ).first()
        if row is None:
            return None

        name = None
        if row.about_patient_user_id:
            user_row = uow.connection.execute(
                text("SELECT full_name FROM users WHERE id = :p AND erased_at IS NULL"),
                {"p": row.about_patient_user_id},
            ).first()
            if user_row:
                name = user_row.full_name

        return NotificationRecord(
            id=row.id,
            user_id=row.user_id,
            about_patient_user_id=row.about_patient_user_id,
            type=row.type,
            content=row.content,
            is_read=row.is_read,
            created_at=row.created_at,
            about_patient_name=name,
        )

    def erase_for_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        uow.connection.execute(
            text("DELETE FROM notifications WHERE user_id = :u OR about_patient_user_id = :u"),
            {"u": user_id},
        )


class SqlScanCursor:
    JOB = "missed_dose_scan"

    def get(self, uow: UnitOfWork) -> datetime | None:
        row = uow.connection.execute(
            text("SELECT scanned_until FROM missed_dose_scan_cursor WHERE job_name = :j"),
            {"j": self.JOB},
        ).first()
        return None if row is None else row.scanned_until

    def advance(self, uow: UnitOfWork, until: datetime) -> None:
        uow.connection.execute(
            text("""
            INSERT INTO missed_dose_scan_cursor (job_name, scanned_until, updated_at)
            VALUES (:j, :u, now())
            ON CONFLICT (job_name) DO UPDATE SET scanned_until = EXCLUDED.scanned_until,
                                                 updated_at = now()
        """),
            {"j": self.JOB, "u": until},
        )


def _record(row) -> DoseLogRecord:
    return DoseLogRecord(
        id=row.id,
        client_uuid=row.client_uuid,
        schedule_id=row.medication_schedule_id,
        scheduled_at=row.scheduled_at,
        taken_at=row.taken_at,
        status=DoseStatus(row.status),
        synced_at=row.synced_at,
    )
