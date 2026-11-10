from dataclasses import dataclass
from uuid import UUID

from drugtime.modules.access.application.authorize import resolve_access
from drugtime.modules.access.application.ports import (
    AccessLog,
    FactsReader,
    PatientCandidates,
    PatientListAudit,
    PatientNames,
)
from drugtime.modules.access.domain.rules import Scope
from drugtime.shared.errors import Forbidden, ServiceUnavailable
from drugtime.shared.uow import UnitOfWork


@dataclass(frozen=True)
class LinkedPatientView:
    patient_id: UUID
    patient_full_name: str | None


def list_linked_patients(
    uow: UnitOfWork,
    *,
    caller_id: UUID,
    caller_is_admin: bool,
    candidates: PatientCandidates,
    facts: FactsReader,
    access_log: AccessLog,
    names: PatientNames,
    request_audit: PatientListAudit,
) -> list[LinkedPatientView]:
    if caller_is_admin:
        request_audit.denied(caller_id)
        raise Forbidden("khong_co_quyen")

    permitted = []
    for patient_id in dict.fromkeys(candidates.ids(uow, caller_id)):
        if patient_id == caller_id:
            continue
        decision = resolve_access(
            uow,
            facts,
            caller_id=caller_id,
            caller_is_admin=False,
            patient_id=patient_id,
            scope=Scope.LINKED_PATIENTS,
        )
        if decision.allowed:
            # Same UoW for all allowed entries, names and the eventual response.
            access_log.append_allowed(
                uow, caller_id, decision.log_role, patient_id, Scope.LINKED_PATIENTS
            )
            permitted.append(patient_id)

    if not permitted:
        request_audit.empty(uow, caller_id)
        return []

    display_names = names.get(uow, permitted)
    if any(patient_id not in display_names for patient_id in permitted):
        # An erased patient can disappear between facts and name projection. Never
        # commit audit for fabricated/omitted result rows; the caller may retry.
        raise ServiceUnavailable("service_unavailable")
    patients = [
        LinkedPatientView(pid, (display_names[pid] or "").strip() or None) for pid in permitted
    ]
    return sorted(
        patients,
        key=lambda p: (p.patient_full_name is None, p.patient_full_name or "", p.patient_id),
    )
