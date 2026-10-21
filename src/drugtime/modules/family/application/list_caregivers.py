from uuid import UUID

from drugtime.modules.family.application.manage_links import deny
from drugtime.modules.family.application.ports import DisplayNames, LinkAudit, Links
from drugtime.modules.family.domain.consent_confirmation import Caregiver
from drugtime.shared.uow import UnitOfWork


def list_caregivers(
    uow: UnitOfWork,
    *,
    actor_id: UUID,
    is_admin: bool,
    links: Links,
    names: DisplayNames,
    audit: LinkAudit,
) -> list[Caregiver]:
    if is_admin:
        deny(audit, actor_id, "list_caregivers")
    active = links.list_caregivers(uow, actor_id)
    display_names = names.get(uow, list({link.family_user_id for link, _ in active}))
    result = [
        Caregiver(
            link.id,
            link.family_user_id,
            display_names.get(link.family_user_id),
            link.sharing_enabled,
            approved_at,
        )
        for link, approved_at in active
    ]
    audit.allowed(uow, actor_id, actor_id, None, "list_caregivers")
    return result
