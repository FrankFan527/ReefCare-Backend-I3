from datetime import datetime

from app.core.enums import CaseStatus
from app.schemas.common import APIModel


class CaseOwnerResponse(APIModel):
    id: int
    display_name: str


class CoordinatorQueueItem(APIModel):
    report_reference: str

    threat: str
    area: str | None = None

    status_label: str

    submitted_at: datetime
    hours_in_queue: int


class CoordinatorQueueResponse(APIModel):
    items: list[CoordinatorQueueItem]

    page: int
    page_size: int
    total: int


class ClaimedCaseResponse(APIModel):
    report_reference: str

    owner: CaseOwnerResponse

    status_code: CaseStatus
    status_label: str

    claimed_at: datetime


class PreciseLocationResponse(APIModel):
    latitude: float | None = None
    longitude: float | None = None

    uncertainty_metres: int | None = None
    confidence_label: str | None = None
    source_label: str | None = None

    relocation_notes: str | None = None


class EvidenceSummary(APIModel):
    evidence_id: int
    media_type: str

    captured_at: datetime | None = None
    uploaded_at: datetime


class CoordinatorCaseResponse(APIModel):
    report_reference: str

    observer_id: int

    threat: str
    description: str

    estimated_depth_metres: float | None = None

    area: str | None = None

    precise_location: PreciseLocationResponse | None = None

    status_code: CaseStatus
    status_label: str

    submitted_at: datetime

    owner: CaseOwnerResponse

    evidence: list[EvidenceSummary]