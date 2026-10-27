from uuid import UUID

from drugtime.modules.adherence.application.ports import SyncCheckpointAccess, SyncCheckpoints
from drugtime.shared.uow import UnitOfWork


def record_sync_checkpoint(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    access: SyncCheckpointAccess,
    checkpoints: SyncCheckpoints,
) -> None:
    """3.19: app báo mọi mục trong hàng chờ liều đã có kết quả cuối. PEP (ghi, chính chủ) chạy
    trước; giờ ghi là giờ server, không bao giờ lùi."""
    access.authorize_sync_checkpoint(uow, caller_id, caller_is_admin)
    checkpoints.record(uow, caller_id)
