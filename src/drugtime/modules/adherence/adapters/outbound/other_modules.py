"""Adapter gọi module khác qua api.py (K16, K23, W07–W09)."""

from datetime import datetime
from uuid import UUID

from drugtime.modules.access import api as access
from drugtime.modules.identity import api as identity
from drugtime.modules.medication import api as medication
from drugtime.shared.uow import UnitOfWork


class AccessGuardAdapter:
    def authorize_history(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None:
        access.authorize(
            uow,
            caller_id=caller_id,
            caller_is_admin=caller_is_admin,
            patient_id=patient_id,
            scope=access.Scope.ADHERENCE,
            action=access.Action.READ,
            audit_self=True,
        )

    # Quyền đọc: hộp thư cảnh báo của người thân dùng hàm này.
    def authorize_adherence(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None:
        access.authorize(
            uow,
            caller_id=caller_id,
            caller_is_admin=caller_is_admin,
            patient_id=patient_id,
            scope=access.Scope.ADHERENCE,
        )

    # Xác nhận liều là ghi dữ liệu sức khỏe: người thân chỉ có quyền đọc (QD-27, 3.19 Q2).
    def authorize_dose_write(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool, patient_id: UUID
    ) -> None:
        access.authorize(
            uow,
            caller_id=caller_id,
            caller_is_admin=caller_is_admin,
            patient_id=patient_id,
            scope=access.Scope.ADHERENCE,
            action=access.Action.WRITE,
        )

    # Checkpoint chỉ ghi cho chính người gọi; không có patient_id từ client.
    def authorize_sync_checkpoint(
        self, uow: UnitOfWork, caller_id: UUID, caller_is_admin: bool
    ) -> None:
        access.authorize(
            uow,
            caller_id=caller_id,
            caller_is_admin=caller_is_admin,
            patient_id=caller_id,
            scope=access.Scope.ADHERENCE,
            action=access.Action.WRITE,
        )

    def caregivers_of(self, uow: UnitOfWork, patient_id: UUID) -> list[UUID]:
        return access.authorized_caregivers(uow, patient_id)


class SchedulesAdapter:
    # Lấy context qua public API của medication để giữ ranh giới sở hữu dữ liệu.
    def alert_context(self, uow: UnitOfWork, schedule_id: int, patient_id: UUID) -> str | None:
        return medication.alert_context(uow, schedule_id, patient_id)

    def owner(self, uow: UnitOfWork, schedule_id: int) -> UUID | None:
        return medication.schedule_owner(uow, schedule_id)

    def ids_of(self, uow: UnitOfWork, user_id: UUID) -> list[int]:
        return medication.schedule_ids_of(uow, user_id)

    def occurrences_between(self, uow: UnitOfWork, start: datetime, end: datetime) -> list:
        return medication.occurrences_between(uow, start, end)


class DeviceTokensAdapter:
    def android_tokens(self, uow: UnitOfWork, user_ids: list[UUID]) -> list[tuple[UUID, str]]:
        return identity.android_tokens(uow, user_ids)

    def remove(self, uow: UnitOfWork, tokens: list[str]) -> None:
        identity.remove_device_tokens(uow, tokens)


# Application chỉ gọi adapter lấy tên sau khi PEP đã cho phép đọc patient tương ứng.
class PatientNamesAdapter:
    def get_patient_name(self, uow: UnitOfWork, patient_id: UUID) -> str | None:
        if uow is None:
            return None
        return identity.user_name(uow, patient_id)
