from collections.abc import Sequence
from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from drugtime.modules.medication.domain.schedule import DoseOccurrence
from drugtime.modules.medication.domain.schedule_changes import ClosedSchedule, NewSchedule
from drugtime.modules.medication.domain.user_medication import (
    DosingMode,
    IntakeTiming,
    MedicationState,
    NewMedication,
    PatientScheduleRecord,
    PendingClosed,
    ScheduleView,
    UserMedicationRecord,
)
from drugtime.shared.uow import UnitOfWork

# Ánh xạ giá trị enum domain (giá trị API) <-> DB.
_MODE_TO_DB = {DosingMode.SCHEDULED: "theo_gio", DosingMode.AS_NEEDED: "khi_can"}
_MODE_FROM_DB = {v: k for k, v in _MODE_TO_DB.items()}
_TIMING_TO_DB = {
    IntakeTiming.BEFORE_MEAL: "truoc_an",
    IntakeTiming.AFTER_MEAL: "sau_an",
    IntakeTiming.ANY_TIME: "khong_lien_quan",
}
_TIMING_FROM_DB = {v: k for k, v in _TIMING_TO_DB.items()}


def _timing_to_db(v: IntakeTiming | None) -> str | None:
    return None if v is None else _TIMING_TO_DB[v]


# Cột được phép cập nhật qua update_fields: tên field -> (biểu thức SET, chuyển giá trị).
_UPDATABLE = {
    "quantity_per_dose": ("quantity_per_dose = :quantity_per_dose", lambda v: v),
    "doses_per_day": ("doses_per_day = :doses_per_day", lambda v: v),
    "stock_quantity": ("stock_quantity = :stock_quantity", lambda v: v),
    "dosing_mode": (
        "dosing_mode = CAST(:dosing_mode AS medication_dosing_mode)",
        lambda v: _MODE_TO_DB[v],
    ),
    "intake_timing": (
        "intake_timing = CAST(:intake_timing AS medication_intake_timing)",
        _timing_to_db,
    ),
}


VIETNAM = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")

# Cùng công thức scheduled_at với lịch sử 3.23 (_HISTORY của adherence) để hai bên khớp tuyệt đối.
# Ngày VN chạy từ start.date - 1 để bắt lịch có giờ uống trước start theo ngày VN của end.
_OCCURRENCES = """
WITH candidate AS (
    SELECT ms.id AS schedule_id, um.user_id AS patient_id, ms.intake_time, ms.days_of_week,
           ms.effective_from, ms.ended_at
    FROM medication_schedules ms
    JOIN user_medications um ON um.id = ms.user_medication_id
    WHERE ms.reminder_enabled
      AND ms.effective_from < :end_at
      AND (ms.ended_at IS NULL OR ms.ended_at > :start_at)
      {prefilter}
)
SELECT c.schedule_id, c.patient_id, occ.scheduled_at
FROM candidate c
CROSS JOIN generate_series(0, CAST(:to_date AS date) - CAST(:from_date AS date))
    AS calendar(day_offset)
CROSS JOIN LATERAL (
    SELECT ((CAST(:from_date AS date) + calendar.day_offset) + c.intake_time)
           AT TIME ZONE :timezone AS scheduled_at
) occ
WHERE EXTRACT(ISODOW FROM CAST(:from_date AS date) + calendar.day_offset) = ANY(c.days_of_week)
  AND occ.scheduled_at >= c.effective_from
  AND (c.ended_at IS NULL OR occ.scheduled_at < c.ended_at)
  AND occ.scheduled_at >= :start_at AND occ.scheduled_at < :end_at
ORDER BY occ.scheduled_at, c.schedule_id
"""

# Lọc trước theo giờ uống (AC11): luôn là tập cha; điều kiện scheduled_at mới chính xác.
_PREFILTER = {
    None: "",
    "same_day": "AND ms.intake_time >= :t_start AND ms.intake_time < :t_end",
    "cross_midnight": "AND (ms.intake_time >= :t_start OR ms.intake_time < :t_end)",
}


def _window_params(start: datetime, end: datetime) -> dict | None:
    """Tham số SQL cho cửa sổ [start, end); None khi cửa sổ rỗng."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start >= end:
        return None
    local_start, local_end = start.astimezone(VIETNAM), end.astimezone(VIETNAM)
    params = {
        "start_at": start,
        "end_at": end,
        "from_date": local_start.date() - timedelta(days=1),
        "to_date": local_end.date(),
        "timezone": "Asia/Ho_Chi_Minh",
        "prefilter": None,
    }
    if end - start < timedelta(days=1):
        params["t_start"] = local_start.time().replace(tzinfo=None)
        params["t_end"] = local_end.time().replace(tzinfo=None)
        same_day = local_start.date() == local_end.date()
        params["prefilter"] = "same_day" if same_day else "cross_midnight"
    return params


class SqlMedication:
    # Ràng buộc schedule với patient ngay khi lấy ID thuốc dùng cho snapshot cảnh báo.
    def alert_medication_id(
        self, uow: UnitOfWork, schedule_id: int, patient_id: UUID
    ) -> int | None:
        row = uow.connection.execute(
            text(
                "SELECT um.medication_id FROM medication_schedules ms "
                "JOIN user_medications um ON um.id = ms.user_medication_id "
                "WHERE ms.id = :s AND um.user_id = :p"
            ),
            {"s": schedule_id, "p": patient_id},
        ).first()
        return None if row is None else row.medication_id

    def schedule_owner(self, uow: UnitOfWork, schedule_id: int) -> UUID | None:
        row = uow.connection.execute(
            text(
                "SELECT um.user_id FROM medication_schedules ms "
                "JOIN user_medications um ON um.id = ms.user_medication_id WHERE ms.id = :s"
            ),
            {"s": schedule_id},
        ).first()
        return None if row is None else row.user_id

    def schedule_ids_of(self, uow: UnitOfWork, user_id: UUID) -> list[int]:
        rows = uow.connection.execute(
            text(
                "SELECT ms.id FROM medication_schedules ms "
                "JOIN user_medications um ON um.id = ms.user_medication_id "
                "WHERE um.user_id = :u"
            ),
            {"u": user_id},
        )
        return [r.id for r in rows]

    def occurrences_between(
        self, uow: UnitOfWork, start: datetime, end: datetime
    ) -> list[DoseOccurrence]:
        """Sinh các lượt uống trong [start, end) từ intake_time + days_of_week (giờ
        Asia/Ho_Chi_Minh), chỉ lấy lịch bật nhắc và scheduled_at trong
        [effective_from, ended_at)."""
        params = _window_params(start, end)
        if params is None:
            return []
        rows = uow.connection.execute(
            text(_OCCURRENCES.format(prefilter=_PREFILTER[params.pop("prefilter")])), params
        )
        return [
            DoseOccurrence(
                schedule_id=r.schedule_id, patient_id=r.patient_id, scheduled_at=r.scheduled_at
            )
            for r in rows
        ]

    # --- Thuốc của người bệnh (task 2.01). Thêm thuốc dùng now() của transaction. Sửa thuốc
    # dùng một mốc `at` lấy sau khi khóa dòng thuốc (xem lock), nên ended_at của lịch cũ
    # bằng effective_from của lịch mới và không nhỏ hơn effective_from của bất kỳ lịch nào.

    def owner_of(self, uow: UnitOfWork, user_medication_id: int) -> UUID | None:
        row = uow.connection.execute(
            text("SELECT user_id FROM user_medications WHERE id = :id AND deleted_at IS NULL"),
            {"id": user_medication_id},
        ).first()
        return None if row is None else row.user_id

    def find_by_client_uuid(
        self, uow: UnitOfWork, user_id: UUID, client_uuid: UUID
    ) -> tuple[int, bool] | None:
        row = uow.connection.execute(
            text(
                "SELECT id, deleted_at IS NOT NULL AS deleted FROM user_medications "
                "WHERE user_id = :u AND client_uuid = :c"
            ),
            {"u": user_id, "c": client_uuid},
        ).first()
        return None if row is None else (row.id, row.deleted)

    def ids_of(self, uow: UnitOfWork, user_id: UUID) -> list[int]:
        rows = uow.connection.execute(
            text(
                "SELECT id FROM user_medications WHERE user_id = :u AND deleted_at IS NULL "
                "ORDER BY id DESC"
            ),
            {"u": user_id},
        )
        return [r.id for r in rows]

    def default_prescription(self, uow: UnitOfWork, user_id: UUID) -> int:
        c = uow.connection
        row = c.execute(
            text(
                "INSERT INTO prescriptions (user_id, entry_source) VALUES (:u, 'mac_dinh') "
                "ON CONFLICT (user_id) WHERE entry_source = 'mac_dinh' DO NOTHING RETURNING id"
            ),
            {"u": user_id},
        ).first()
        if row is None:
            row = c.execute(
                text(
                    "SELECT id FROM prescriptions WHERE user_id = :u AND entry_source = 'mac_dinh'"
                ),
                {"u": user_id},
            ).one()
        return row.id

    def insert(
        self,
        uow: UnitOfWork,
        user_id: UUID,
        prescription_id: int,
        cmd: NewMedication,
        has_interaction_data: bool,
    ) -> int | None:
        row = uow.connection.execute(
            text(
                "INSERT INTO user_medications (user_id, prescription_id, medication_id, "
                "entry_method, confirmation_status, quantity_per_dose, doses_per_day, "
                "has_interaction_data, dosing_mode, intake_timing, stock_quantity, client_uuid) "
                "VALUES (:u, :p, :m, 'thu_cong', 'da_xac_nhan', :q, :d, :h, "
                "CAST(:mode AS medication_dosing_mode), "
                "CAST(:timing AS medication_intake_timing), :stock, :c) "
                "ON CONFLICT ON CONSTRAINT user_medications_client_uuid_uq DO NOTHING "
                "RETURNING id"
            ),
            {
                "u": user_id,
                "p": prescription_id,
                "m": cmd.medication_id,
                "q": cmd.quantity_per_dose,
                "d": cmd.doses_per_day,
                "h": has_interaction_data,
                "mode": _MODE_TO_DB[cmd.dosing_mode],
                "timing": _timing_to_db(cmd.intake_timing),
                "stock": cmd.stock_quantity,
                "c": cmd.client_uuid,
            },
        ).first()
        return None if row is None else row.id

    def insert_schedules(
        self,
        uow: UnitOfWork,
        user_medication_id: int,
        intake_times: tuple[time, ...],
        days_of_week: tuple[int, ...],
        effective_from: datetime | None = None,
    ) -> None:
        uow.connection.execute(
            text(
                "INSERT INTO medication_schedules "
                "(user_medication_id, intake_time, days_of_week, effective_from) "
                "VALUES (:id, :t, CAST(:days AS smallint[]), COALESCE(:at, now()))"
            ),
            [
                {"id": user_medication_id, "t": t, "days": list(days_of_week), "at": effective_from}
                for t in intake_times
            ],
        )

    def lock(self, uow: UnitOfWork, user_medication_id: int) -> tuple[MedicationState, datetime]:
        c = uow.connection
        row = c.execute(
            text(
                "SELECT dosing_mode, ended_at, deleted_at FROM user_medications "
                "WHERE id = :id FOR UPDATE"
            ),
            {"id": user_medication_id},
        ).one()
        # Câu lệnh riêng, chạy sau khi đã có khóa: clock_timestamp() là giờ thật lúc này.
        at = c.execute(text("SELECT clock_timestamp()")).scalar_one()
        # Đọc lịch sau khi có khóa: request ghi khác trên thuốc này đã commit xong (task 2.04).
        rows = c.execute(
            text(
                "SELECT id, intake_time, days_of_week, reminder_enabled, effective_from, ended_at "
                "FROM medication_schedules WHERE user_medication_id = :id "
                "AND (ended_at IS NULL OR ended_at > :at) ORDER BY intake_time, id"
            ),
            {"id": user_medication_id, "at": at},
        ).all()
        open_schedules = tuple(
            ScheduleView(
                id=s.id,
                intake_time=s.intake_time,
                days_of_week=tuple(sorted(s.days_of_week)),
                reminder_enabled=s.reminder_enabled,
                effective_from=s.effective_from,
            )
            for s in rows
            if s.ended_at is None
        )
        state = MedicationState(
            dosing_mode=_MODE_FROM_DB[row.dosing_mode],
            stopped=row.ended_at is not None,
            open_days_of_week=open_schedules[0].days_of_week if open_schedules else None,
            deleted=row.deleted_at is not None,
            open_schedules=open_schedules,
            pending_closed=tuple(
                PendingClosed(s.intake_time, s.ended_at) for s in rows if s.ended_at is not None
            ),
            ended_at=row.ended_at,
        )
        return state, at

    def update_fields(self, uow: UnitOfWork, user_medication_id: int, fields: dict) -> None:
        sets, params = [], {"id": user_medication_id}
        for name, value in fields.items():
            expr, convert = _UPDATABLE[name]  # tên ngoài danh sách -> KeyError, không ghép SQL lạ
            sets.append(expr)
            params[name] = convert(value)
        uow.connection.execute(
            text("UPDATE user_medications SET " + ", ".join(sets) + " WHERE id = :id"), params
        )

    def closed_by_stop(
        self, uow: UnitOfWork, user_medication_id: int, stopped_at: datetime
    ) -> tuple[ClosedSchedule, ...]:
        """Lịch đóng bởi lần ngừng tại stopped_at (ứng viên mở lại khi dùng lại thuốc)."""
        rows = uow.connection.execute(
            text(
                "SELECT id, intake_time, days_of_week, reminder_enabled, effective_from, ended_at "
                "FROM medication_schedules "
                "WHERE user_medication_id = :id AND closed_by_stop_at = :stopped "
                "ORDER BY id"
            ),
            {"id": user_medication_id, "stopped": stopped_at},
        )
        return tuple(
            ClosedSchedule(
                id=r.id,
                intake_time=r.intake_time,
                days_of_week=tuple(sorted(r.days_of_week)),
                reminder_enabled=r.reminder_enabled,
                effective_from=r.effective_from,
                ended_at=r.ended_at,
            )
            for r in rows
        )

    def resume(self, uow: UnitOfWork, user_medication_id: int) -> None:
        uow.connection.execute(
            text("UPDATE user_medications SET ended_at = NULL WHERE id = :id"),
            {"id": user_medication_id},
        )

    def close_schedule(
        self,
        uow: UnitOfWork,
        schedule_id: int,
        ended_at: datetime,
        stopped_at: datetime | None = None,
    ) -> None:
        uow.connection.execute(
            text(
                "UPDATE medication_schedules SET ended_at = :e, closed_by_stop_at = :stop "
                "WHERE id = :s AND ended_at IS NULL"
            ),
            {"s": schedule_id, "e": ended_at, "stop": stopped_at},
        )

    def add_schedules(
        self, uow: UnitOfWork, user_medication_id: int, schedules: Sequence[NewSchedule]
    ) -> None:
        """Lịch mới với effective_from, reminder_enabled do domain tính (task 2.04)."""
        if not schedules:
            return
        uow.connection.execute(
            text(
                "INSERT INTO medication_schedules "
                "(user_medication_id, intake_time, days_of_week, reminder_enabled, effective_from) "
                "VALUES (:id, :t, CAST(:days AS smallint[]), :r, :at)"
            ),
            [
                {
                    "id": user_medication_id,
                    "t": s.intake_time,
                    "days": list(s.days_of_week),
                    "r": s.reminder_enabled,
                    "at": s.effective_from,
                }
                for s in schedules
            ],
        )

    def patient_schedules(
        self, uow: UnitOfWork, patient_id: UUID, after_id: int, limit: int
    ) -> list[PatientScheduleRecord]:
        """Lịch đang mở hoặc đóng trong 30 ngày của thuốc chưa xoá, id tăng dần (QD-18)."""
        rows = uow.connection.execute(
            text(
                "SELECT ms.id, ms.user_medication_id, um.medication_id, um.quantity_per_dose, "
                "um.doses_per_day, um.intake_timing, ms.intake_time, ms.days_of_week, "
                "ms.reminder_enabled, ms.effective_from, ms.ended_at "
                "FROM medication_schedules ms "
                "JOIN user_medications um ON um.id = ms.user_medication_id "
                "WHERE um.user_id = :p AND um.deleted_at IS NULL "
                "AND (ms.ended_at IS NULL OR ms.ended_at > now() - interval '30 days') "
                "AND ms.id > :after ORDER BY ms.id LIMIT :n"
            ),
            {"p": patient_id, "after": after_id, "n": limit},
        )
        return [
            PatientScheduleRecord(
                id=r.id,
                user_medication_id=r.user_medication_id,
                medication_id=r.medication_id,
                quantity_per_dose=r.quantity_per_dose,
                doses_per_day=r.doses_per_day,
                intake_timing=None if r.intake_timing is None else _TIMING_FROM_DB[r.intake_timing],
                intake_time=r.intake_time,
                days_of_week=tuple(sorted(r.days_of_week)),
                reminder_enabled=r.reminder_enabled,
                effective_from=r.effective_from,
                ended_at=r.ended_at,
            )
            for r in rows
        ]

    def stop(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None:
        uow.connection.execute(
            text("UPDATE user_medications SET ended_at = :at WHERE id = :id AND ended_at IS NULL"),
            {"id": user_medication_id, "at": at},
        )

    def mark_deleted(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None:
        uow.connection.execute(
            text(
                "UPDATE user_medications SET deleted_at = :at WHERE id = :id AND deleted_at IS NULL"
            ),
            {"id": user_medication_id, "at": at},
        )

    def read(self, uow: UnitOfWork, user_medication_id: int) -> UserMedicationRecord:
        c = uow.connection
        row = c.execute(
            text(
                "SELECT id, user_id, medication_id, dosing_mode, quantity_per_dose, "
                "doses_per_day, intake_timing, stock_quantity, has_interaction_data, ended_at "
                "FROM user_medications WHERE id = :id"
            ),
            {"id": user_medication_id},
        ).one()
        schedules = c.execute(
            text(
                "SELECT id, intake_time, days_of_week, reminder_enabled, effective_from "
                "FROM medication_schedules WHERE user_medication_id = :id AND ended_at IS NULL "
                "ORDER BY intake_time, id"
            ),
            {"id": user_medication_id},
        )
        return UserMedicationRecord(
            id=row.id,
            user_id=row.user_id,
            medication_id=row.medication_id,
            dosing_mode=_MODE_FROM_DB[row.dosing_mode],
            quantity_per_dose=row.quantity_per_dose,
            doses_per_day=row.doses_per_day,
            intake_timing=None if row.intake_timing is None else _TIMING_FROM_DB[row.intake_timing],
            stock_quantity=row.stock_quantity,
            has_interaction_data=row.has_interaction_data,
            ended_at=row.ended_at,
            schedules=tuple(
                ScheduleView(
                    id=s.id,
                    intake_time=s.intake_time,
                    days_of_week=tuple(sorted(s.days_of_week)),
                    reminder_enabled=s.reminder_enabled,
                    effective_from=s.effective_from,
                )
                for s in schedules
            ),
        )

    def erase(self, uow: UnitOfWork, user_id: UUID) -> None:
        c = uow.connection
        c.execute(
            text(
                "DELETE FROM medication_schedules WHERE user_medication_id IN "
                "(SELECT id FROM user_medications WHERE user_id = :u)"
            ),
            {"u": user_id},
        )
        c.execute(text("DELETE FROM user_medications WHERE user_id = :u"), {"u": user_id})
        c.execute(text("DELETE FROM prescriptions WHERE user_id = :u"), {"u": user_id})
        c.execute(text("DELETE FROM user_conditions WHERE user_id = :u"), {"u": user_id})
