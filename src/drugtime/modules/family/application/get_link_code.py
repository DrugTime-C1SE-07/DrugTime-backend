from collections.abc import Callable
from uuid import UUID

from drugtime.modules.family.application.ports import LinkCodes
from drugtime.modules.family.domain.link_code import LinkCode, generate_code
from drugtime.shared.errors import Forbidden, ServiceUnavailable
from drugtime.shared.uow import UnitOfWork

MAX_ATTEMPTS = 5


def get_link_code(
    uow: UnitOfWork,
    *,
    user_id: UUID,
    is_admin: bool,
    codes: LinkCodes,
    generate: Callable[[], str] = generate_code,
    max_attempts: int = MAX_ATTEMPTS,
) -> LinkCode:
    """Mã cố định của user (QD-04): có thì trả, chưa có thì sinh một lần."""
    if is_admin:
        # Tài khoản admin tách khỏi tài khoản cá nhân (QD-44).
        raise Forbidden("khong_co_quyen")
    existing = codes.find_by_patient(uow, user_id)
    if existing is not None:
        return LinkCode(patient_user_id=user_id, code=existing)
    for _ in range(max_attempts):
        stored = codes.insert_if_absent(uow, user_id, generate())
        if stored is not None:
            return LinkCode(patient_user_id=user_id, code=stored)
    raise ServiceUnavailable("link_code_unavailable")
