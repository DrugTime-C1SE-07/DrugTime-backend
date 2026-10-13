from uuid import UUID

from sqlalchemy import text

from drugtime.shared.uow import UnitOfWork

_SELECT_BY_PATIENT = text("SELECT code FROM link_codes WHERE patient_user_id = :patient_id")

# Không chỉ định cột xung đột: bao cả UNIQUE (patient_user_id) và UNIQUE (code).
# Request đồng thời cho cùng user chờ bên kia commit rồi không ghi gì (READ COMMITTED).
_INSERT_IF_ABSENT = text("""
INSERT INTO link_codes (patient_user_id, code)
VALUES (:patient_id, :code)
ON CONFLICT DO NOTHING
RETURNING code
""")


class SqlLinkCodes:
    def find_by_patient(self, uow: UnitOfWork, patient_id: UUID) -> str | None:
        return uow.connection.execute(_SELECT_BY_PATIENT, {"patient_id": patient_id}).scalar()

    def insert_if_absent(self, uow: UnitOfWork, patient_id: UUID, code: str) -> str | None:
        inserted = uow.connection.execute(
            _INSERT_IF_ABSENT, {"patient_id": patient_id, "code": code}
        ).scalar()
        if inserted is not None:
            return inserted
        # Không ghi được: user đã có mã (request khác vừa tạo), hoặc mã trùng của user khác.
        return self.find_by_patient(uow, patient_id)
