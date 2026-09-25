from uuid import UUID

from sqlalchemy import text

from drugtime.shared.uow import UnitOfWork


def erase(uow: UnitOfWork, user_id: UUID) -> None:
    c = uow.connection
    snapshots = "SELECT id FROM regimen_analysis_snapshots WHERE user_id = :u"
    findings = f"SELECT id FROM regimen_analysis_findings WHERE snapshot_id IN ({snapshots})"
    c.execute(text("DELETE FROM user_recommendations WHERE user_id = :u"), {"u": user_id})
    c.execute(
        text(f"DELETE FROM regimen_analysis_finding_medications WHERE finding_id IN ({findings})"),
        {"u": user_id},
    )
    c.execute(
        text(f"DELETE FROM regimen_analysis_findings WHERE snapshot_id IN ({snapshots})"),
        {"u": user_id},
    )
    c.execute(text("DELETE FROM regimen_analysis_snapshots WHERE user_id = :u"), {"u": user_id})
