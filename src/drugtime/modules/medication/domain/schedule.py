from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class DoseOccurrence:
    """Một lượt uống theo lịch: medication_schedule_id tại scheduled_at (UTC)."""

    schedule_id: UUID
    patient_id: UUID
    scheduled_at: datetime
