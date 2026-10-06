from datetime import datetime
from uuid import UUID

from sqlalchemy import text

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

    def erase_for_schedules(self, uow: UnitOfWork, schedule_ids: list[int]) -> None:
        if schedule_ids:
            uow.connection.execute(
                text("DELETE FROM dose_logs WHERE medication_schedule_id = ANY(:ids)"),
                {"ids": schedule_ids},
            )


class SqlNotifications:
    def create_missed_alert(
        self, uow: UnitOfWork, recipient_id: UUID, patient_id: UUID, dedupe_key: str
    ) -> UUID | None:
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
                "content": "Chưa ghi nhận liều thuốc đúng giờ",
            },
        ).first()
        return None if row is None else row.id

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
