from datetime import datetime, time
from uuid import UUID

from sqlalchemy import text

from drugtime.modules.medication.domain.schedule import DoseOccurrence
from drugtime.modules.medication.domain.user_medication import (
    DosingMode,
    IntakeTiming,
    MedicationState,
    NewMedication,
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


class SqlMedication:
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
        Asia/Ho_Chi_Minh), chỉ lấy scheduled_at >= effective_from và reminder_enabled."""
        raise NotImplementedError  # TODO: task missed-dose scan (generate_series theo ngày)

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
        days = c.execute(
            text(
                "SELECT days_of_week FROM medication_schedules "
                "WHERE user_medication_id = :id AND ended_at IS NULL "
                "ORDER BY intake_time, id LIMIT 1"
            ),
            {"id": user_medication_id},
        ).first()
        state = MedicationState(
            dosing_mode=_MODE_FROM_DB[row.dosing_mode],
            stopped=row.ended_at is not None,
            open_days_of_week=None if days is None else tuple(sorted(days.days_of_week)),
            deleted=row.deleted_at is not None,
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

    def close_open_schedules(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None:
        uow.connection.execute(
            text(
                "UPDATE medication_schedules SET ended_at = :at "
                "WHERE user_medication_id = :id AND ended_at IS NULL"
            ),
            {"id": user_medication_id, "at": at},
        )

    def stop(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None:
        uow.connection.execute(
            text("UPDATE user_medications SET ended_at = :at WHERE id = :id AND ended_at IS NULL"),
            {"id": user_medication_id, "at": at},
        )

    def mark_deleted(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> None:
        uow.connection.execute(
            text(
                "UPDATE user_medications SET deleted_at = :at "
                "WHERE id = :id AND deleted_at IS NULL"
            ),
            {"id": user_medication_id, "at": at},
        )

    def reactivate(self, uow: UnitOfWork, user_medication_id: int, at: datetime) -> int:
        c = uow.connection
        # Lịch đóng lúc ngừng có ended_at đúng bằng ended_at của thuốc (stop và
        # close_open_schedules dùng cùng mốc `at`). Lịch đóng ở lần đổi giờ trước đó thì không.
        reopened = c.execute(
            text(
                "INSERT INTO medication_schedules "
                "(user_medication_id, intake_time, days_of_week, reminder_enabled, effective_from) "
                "SELECT ms.user_medication_id, ms.intake_time, ms.days_of_week, "
                "ms.reminder_enabled, :at "
                "FROM medication_schedules ms JOIN user_medications um "
                "ON um.id = ms.user_medication_id "
                "WHERE um.id = :id AND ms.ended_at = um.ended_at "
                "ORDER BY ms.intake_time, ms.id"
            ),
            {"id": user_medication_id, "at": at},
        ).rowcount
        c.execute(
            text("UPDATE user_medications SET ended_at = NULL WHERE id = :id"),
            {"id": user_medication_id},
        )
        return reopened

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
