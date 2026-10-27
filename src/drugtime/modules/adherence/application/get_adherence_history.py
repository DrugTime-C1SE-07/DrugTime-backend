from datetime import date, datetime
from uuid import UUID

from drugtime.modules.adherence.application.ports import AdherenceHistoryReader, HistoryAccess
from drugtime.modules.adherence.domain.history import GroupBy, History, build_history, resolve_range
from drugtime.shared.uow import UnitOfWork


def get_adherence_history(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    patient_id: UUID | None,
    start: date | None,
    end: date | None,
    group_by: GroupBy,
    as_of: datetime,
    access: HistoryAccess,
    reader: AdherenceHistoryReader,
) -> History:
    period = resolve_range(start, end, as_of)
    target = patient_id if patient_id is not None else caller_id
    access.authorize_history(uow, caller_id, caller_is_admin, target)
    rows, synced_at = reader.read(uow, target, period, as_of)
    return build_history(
        rows,
        patient_id=target,
        period=period,
        group_by=group_by,
        as_of=as_of,
        synced_at=synced_at,
    )
