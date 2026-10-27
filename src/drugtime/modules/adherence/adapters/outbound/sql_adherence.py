from datetime import datetime, time, timedelta
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
from drugtime.modules.adherence.domain.history import TIMEZONE, VIETNAM, HistoryRange, HistoryRow
from drugtime.modules.medication.api import DoseOccurrence
from drugtime.shared.uow import UnitOfWork

_SELECT_BY_CLIENT_UUID = text("""
SELECT id, medication_schedule_id, scheduled_at, taken_at, status, client_uuid, synced_at
FROM dose_logs
WHERE client_uuid = :client_uuid
""")

# Cài đúng domain.dose.status_for_confirmation (quá +120 phút lưu bo_lo, không ghi taken_at) và
# status_after_confirmation: dòng bo_lo nhận trạng thái tính từ taken_at; dòng đã xác nhận
# giữ nguyên.
_UPSERT_CONFIRMATION = text("""
INSERT INTO dose_logs (medication_schedule_id, scheduled_at, taken_at, status, client_uuid,
                       synced_at)
VALUES (:schedule_id, :scheduled_at, :taken_at, :status, :client_uuid, now())
ON CONFLICT (medication_schedule_id, scheduled_at) DO UPDATE SET
    status = CASE WHEN dose_logs.status = 'bo_lo' AND EXCLUDED.status <> 'bo_lo'
                  THEN EXCLUDED.status ELSE dose_logs.status END,
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

# One statement snapshot for both generated occurrences and recorded keys, including closed
# schedules and soft-deleted medications. Authorization is enforced before this reader.
_HISTORY = text("""
WITH patient_schedules AS (
    SELECT ms.id AS schedule_id, ms.intake_time, ms.days_of_week,
           ms.effective_from, ms.ended_at, um.medication_id, m.name AS medication_name
    FROM user_medications um
    JOIN medication_schedules ms ON ms.user_medication_id = um.id
    JOIN medications m ON m.id = um.medication_id
    WHERE um.user_id = :patient_id
), generated AS (
    SELECT s.schedule_id, occ.scheduled_at
    FROM patient_schedules s
    CROSS JOIN generate_series(0, CAST(:to_date AS date) - CAST(:from_date AS date))
        AS calendar(day_offset)
    CROSS JOIN LATERAL (
        SELECT ((CAST(:from_date AS date) + calendar.day_offset) + s.intake_time)
               AT TIME ZONE :timezone AS scheduled_at
    ) occ
    WHERE EXTRACT(ISODOW FROM CAST(:from_date AS date) + calendar.day_offset)
          = ANY(s.days_of_week)
      AND occ.scheduled_at >= s.effective_from
      AND (s.ended_at IS NULL OR occ.scheduled_at < s.ended_at)
      AND occ.scheduled_at <= :as_of
), recorded AS (
    SELECT dl.medication_schedule_id AS schedule_id, dl.scheduled_at
    FROM dose_logs dl
    JOIN patient_schedules s ON s.schedule_id = dl.medication_schedule_id
    WHERE dl.scheduled_at >= :start_at AND dl.scheduled_at < :end_at
      AND dl.scheduled_at <= :as_of
), occurrence_keys AS (
    SELECT schedule_id, scheduled_at FROM generated
    UNION
    SELECT schedule_id, scheduled_at FROM recorded
)
SELECT s.medication_id, s.medication_name, k.schedule_id, k.scheduled_at,
       dl.taken_at, dl.status
FROM occurrence_keys k
JOIN patient_schedules s ON s.schedule_id = k.schedule_id
LEFT JOIN dose_logs dl ON dl.medication_schedule_id = k.schedule_id
                     AND dl.scheduled_at = k.scheduled_at
""")


class SqlAdherenceHistory:
    def read(
        self, uow: UnitOfWork, patient_id: UUID, period: HistoryRange, as_of: datetime
    ) -> tuple[list[HistoryRow], datetime | None]:
        # Đọc checkpoint trước các liều: checkpoint chỉ tăng, nên đồng bộ chen giữa hai câu chỉ làm
        # kết quả nghiêng về chua_xac_minh (an toàn), không bao giờ suy bo_lo quá sớm.
        synced_at = SqlSyncCheckpoints().get(uow, patient_id)
        rows = uow.connection.execute(
            _HISTORY,
            {
                "patient_id": patient_id,
                "from_date": period.start,
                "to_date": period.end,
                "timezone": TIMEZONE,
                "start_at": datetime.combine(period.start, time.min, VIETNAM),
                "end_at": datetime.combine(period.end + timedelta(days=1), time.min, VIETNAM),
                "as_of": as_of,
            },
        )
        return [
            HistoryRow(
                medication_id=row.medication_id,
                medication_name=row.medication_name,
                schedule_id=row.schedule_id,
                scheduled_at=row.scheduled_at,
                taken_at=row.taken_at,
                status=DoseStatus(row.status) if row.status is not None else None,
            )
            for row in rows
        ], synced_at


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
        uow,
        recipient_id,
        patient_id,
        dedupe_key,
        content=None,
        *,
        medication_name,
        scheduled_at,
    ):
        row = uow.connection.execute(
            text("""
            INSERT INTO notifications (user_id, about_patient_user_id, type, content,
                                       dedupe_key, medication_name, scheduled_at)
            VALUES (:r, :p, 'canh_bao_bo_lo_lieu_nguoi_than', :content, :k, :name, :at)
            ON CONFLICT (dedupe_key) DO NOTHING RETURNING id
        """),
            {
                "r": recipient_id,
                "p": patient_id,
                "k": dedupe_key,
                "content": content or "Chưa ghi nhận liều thuốc đúng giờ",
                "name": medication_name,
                "at": scheduled_at,
            },
        ).first()
        return None if row is None else row.id

    # Trước PEP chỉ trả ID định tuyến; chưa đọc nội dung hay snapshot sức khỏe.
    def metadata(self, uow, user_id, notification_id=None):
        rows = uow.connection.execute(
            text("""
            SELECT id, about_patient_user_id FROM notifications
            WHERE user_id = :u AND (CAST(:id AS bigint) IS NULL OR id = CAST(:id AS bigint))
        """),
            {"u": user_id, "id": notification_id},
        )
        return [(r.id, r.about_patient_user_id) for r in rows]

    # Caller cung cấp tập ID đã qua PEP; vẫn giới hạn theo recipient trong truy vấn.
    def authorized_records(self, uow, user_id, ids):
        if not ids:
            return []
        rows = uow.connection.execute(
            text("""
            SELECT id, user_id, about_patient_user_id, type, content, is_read,
                   created_at, medication_name, scheduled_at
            FROM notifications WHERE user_id = :u AND id = ANY(:ids)
            ORDER BY created_at DESC, id DESC
        """),
            {"u": user_id, "ids": ids},
        )
        return [self._notification(r) for r in rows]

    def mark_as_read(self, uow, notification_id, user_id, is_read=True):
        row = uow.connection.execute(
            text("""
            UPDATE notifications SET is_read = :ir
            WHERE id = :id AND user_id = :u
            RETURNING id, user_id, about_patient_user_id, type, content, is_read,
                      created_at, medication_name, scheduled_at
        """),
            {"id": notification_id, "u": user_id, "ir": is_read},
        ).first()
        return None if row is None else self._notification(row)

    @staticmethod
    def _notification(row):
        return NotificationRecord(
            id=row.id,
            user_id=row.user_id,
            about_patient_user_id=row.about_patient_user_id,
            type=row.type,
            content=row.content,
            is_read=row.is_read,
            created_at=row.created_at,
            medication_name=row.medication_name,
            scheduled_at=row.scheduled_at,
        )

    def erase_for_user(self, uow, user_id):
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


class SqlSyncCheckpoints:
    """dose_sync_checkpoints: API ghi (giờ DB, không lùi), Worker đọc và xóa (QD-35)."""

    def record(self, uow: UnitOfWork, user_id: UUID) -> None:
        uow.connection.execute(
            text("""
            INSERT INTO dose_sync_checkpoints (user_id, synced_at) VALUES (:u, now())
            ON CONFLICT (user_id) DO UPDATE
            SET synced_at = GREATEST(dose_sync_checkpoints.synced_at, EXCLUDED.synced_at)
        """),
            {"u": user_id},
        )

    def get(self, uow: UnitOfWork, user_id: UUID) -> datetime | None:
        return self.get_many(uow, [user_id]).get(user_id)

    def get_many(self, uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, datetime]:
        if not user_ids:
            return {}
        rows = uow.connection.execute(
            text("SELECT user_id, synced_at FROM dose_sync_checkpoints WHERE user_id = ANY(:ids)"),
            {"ids": list(user_ids)},
        )
        return {r.user_id: r.synced_at for r in rows}

    def erase_for_user(self, uow: UnitOfWork, user_id: UUID) -> None:
        uow.connection.execute(
            text("DELETE FROM dose_sync_checkpoints WHERE user_id = :u"), {"u": user_id}
        )


# Liều đã có dòng dose_logs (xác nhận hoặc bo_lo) không bao giờ vào hàng chờ, nên không gõ cửa.
_ADD_PENDING = text("""
INSERT INTO missed_dose_pending_verifications
    (medication_schedule_id, scheduled_at, patient_user_id)
SELECT :s, :at, :p
WHERE NOT EXISTS (
    SELECT 1 FROM dose_logs WHERE medication_schedule_id = :s AND scheduled_at = :at
)
ON CONFLICT (medication_schedule_id, scheduled_at) DO NOTHING
RETURNING 1
""")

# Cùng ngưỡng với lượt quét: checkpoint >= hạn chót (bằng đúng là đã xác minh), now > hạn chót.
_VERIFIED_PENDING = text("""
SELECT v.medication_schedule_id AS schedule_id, v.patient_user_id AS patient_id, v.scheduled_at
FROM missed_dose_pending_verifications v
JOIN dose_sync_checkpoints c ON c.user_id = v.patient_user_id
WHERE c.synced_at >= v.scheduled_at + :window
  AND v.scheduled_at + :window < :now
ORDER BY v.scheduled_at, v.medication_schedule_id
""")


class SqlPendingVerifications:
    """Hàng việc nội bộ của Worker (không phải trạng thái liều)."""

    def __init__(self, window: timedelta) -> None:
        self._window = window

    def add(self, uow: UnitOfWork, occ) -> bool:
        row = uow.connection.execute(
            _ADD_PENDING, {"s": occ.schedule_id, "at": occ.scheduled_at, "p": occ.patient_id}
        ).first()
        return row is not None

    def verified(self, uow: UnitOfWork, now: datetime) -> list[DoseOccurrence]:
        rows = uow.connection.execute(_VERIFIED_PENDING, {"window": self._window, "now": now})
        return [
            DoseOccurrence(
                schedule_id=r.schedule_id, patient_id=r.patient_id, scheduled_at=r.scheduled_at
            )
            for r in rows
        ]

    def remove(self, uow: UnitOfWork, occ) -> None:
        uow.connection.execute(
            text(
                "DELETE FROM missed_dose_pending_verifications "
                "WHERE medication_schedule_id = :s AND scheduled_at = :at"
            ),
            {"s": occ.schedule_id, "at": occ.scheduled_at},
        )

    def purge_recorded(self, uow: UnitOfWork) -> None:
        uow.connection.execute(
            text("""
            DELETE FROM missed_dose_pending_verifications v USING dose_logs d
            WHERE d.medication_schedule_id = v.medication_schedule_id
              AND d.scheduled_at = v.scheduled_at
        """)
        )

    def erase_for_patient(self, uow: UnitOfWork, user_id: UUID) -> None:
        uow.connection.execute(
            text("DELETE FROM missed_dose_pending_verifications WHERE patient_user_id = :u"),
            {"u": user_id},
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
