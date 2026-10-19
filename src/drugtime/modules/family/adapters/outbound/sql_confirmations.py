from datetime import datetime

from sqlalchemy import text

from drugtime.modules.family.domain.consent_confirmation import ConsentConfirmation
from drugtime.modules.family.domain.link import FamilyLink
from drugtime.shared.uow import UnitOfWork


class SqlConfirmations:
    def get(self, uow: UnitOfWork, link: FamilyLink) -> ConsentConfirmation | None:
        row = uow.connection.execute(
            text(
                "SELECT id, link_id, patient_user_id, family_user_id, purpose, "
                "document_version, confirmed_at FROM family_link_consent_confirmations "
                "WHERE link_id = :l AND patient_user_id = :p AND family_user_id = :f "
                "AND purpose = 'family_sharing'"
            ),
            {"l": link.id, "p": link.patient_user_id, "f": link.family_user_id},
        ).first()
        return None if row is None else ConsentConfirmation(**row._mapping)

    def insert(
        self, uow: UnitOfWork, link: FamilyLink, document_version: str
    ) -> ConsentConfirmation:
        row = uow.connection.execute(
            text(
                "INSERT INTO family_link_consent_confirmations "
                "(link_id, patient_user_id, family_user_id, purpose, document_version) "
                "VALUES (:l, :p, :f, 'family_sharing', :v) "
                "RETURNING id, link_id, patient_user_id, family_user_id, purpose, "
                "document_version, confirmed_at"
            ),
            {
                "l": link.id,
                "p": link.patient_user_id,
                "f": link.family_user_id,
                "v": document_version,
            },
        ).one()
        return ConsentConfirmation(**row._mapping)

    def now(self, uow: UnitOfWork) -> datetime:
        return uow.connection.execute(text("SELECT clock_timestamp()")).scalar_one()
