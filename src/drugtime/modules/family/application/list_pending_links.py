from uuid import UUID

from drugtime.modules.family.application.manage_links import deny
from drugtime.modules.family.application.ports import DisplayNames, LinkAudit, Links
from drugtime.modules.family.domain.consent_confirmation import PendingLink
from drugtime.shared.uow import UnitOfWork


def list_pending_links(
    uow: UnitOfWork,
    *,
    actor_id: UUID,
    is_admin: bool,
    links: Links,
    names: DisplayNames,
    audit: LinkAudit,
) -> list[PendingLink]:
    if is_admin:
        deny(audit, actor_id, "list_pending")
    pending = links.list_pending(uow, actor_id)
    display_names = names.get(uow, list({link.family_user_id for link in pending}))
    result = [
        PendingLink(
            link.id, link.family_user_id, display_names.get(link.family_user_id), link.linked_at
        )
        for link in pending
    ]
    audit.allowed(uow, actor_id, actor_id, None, "list_pending")
    return result
