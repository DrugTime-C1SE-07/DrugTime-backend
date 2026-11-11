from uuid import UUID

from drugtime.modules.access.application.ports import AccessLog, FactsReader
from drugtime.modules.access.domain.rules import SCOPE_PURPOSE, Action, Decision, Scope, decide
from drugtime.shared.errors import Forbidden
from drugtime.shared.uow import UnitOfWork


def resolve_access(
    uow: UnitOfWork,
    facts: FactsReader,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    patient_id: UUID,
    scope: Scope,
    action: Action = Action.READ,
    audit_self: bool = False,
) -> Decision:
    """Shared PEP resolution; a decision alone never reads a payload or persists audit."""
    return decide(
        facts.read(uow, caller_id, caller_is_admin, patient_id, scope),
        action,
        audit_self=(scope is Scope.HEALTH_PROFILE) or audit_self,
        scope=scope,
    )


def authorize(
    uow: UnitOfWork,
    facts: FactsReader,
    log: AccessLog,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    patient_id: UUID,
    scope: Scope,
    action: Action = Action.READ,
    audit_self: bool = False,
) -> None:
    decision = resolve_access(
        uow,
        facts,
        caller_id=caller_id,
        caller_is_admin=caller_is_admin,
        patient_id=patient_id,
        scope=scope,
        action=action,
        audit_self=audit_self,
    )
    if decision.allowed:
        if decision.log_role is not None:
            # Cùng transaction với request: ghi log lỗi thì request lỗi (fail-closed).
            log.append_allowed(uow, caller_id, decision.log_role, patient_id, scope)
        return
    if decision.log_role is not None:
        log.append_denied(caller_id, decision.log_role, patient_id, scope, decision.reason or "")
    raise Forbidden(decision.reason or "forbidden")


def authorized_caregivers(
    uow: UnitOfWork, facts: FactsReader, patient_id: UUID, scope: Scope = Scope.ADHERENCE
) -> list[UUID]:
    """Worker: người nhận cảnh báo theo đúng điều kiện nhánh family; không ghi log (CD6)."""
    if facts.pending_deletion(uow, patient_id):
        return []
    if not facts.has_consent(uow, patient_id, "family_sharing"):
        return []
    if not facts.has_consent(uow, patient_id, SCOPE_PURPOSE[scope]):
        return []
    return facts.sharing_family_ids(uow, patient_id)
