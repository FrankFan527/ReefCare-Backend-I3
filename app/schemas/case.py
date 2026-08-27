from datetime import datetime

from pydantic import BaseModel

from app.core.enums import CaseStatus


class CaseOwnerResponse(BaseModel):
    id: int
    display_name: str


class CoordinatorQueueItem(BaseModel):
    report_id: int
    report_reference: str

    threat: str
    area: str | None = None

    # v_unclaimed_queue currently exposes
    # case_status.internal_label.
    status_label: str

    submitted_at: datetime
    hours_in_queue: int


class CoordinatorQueueResponse(BaseModel):
    items: list[CoordinatorQueueItem]

    page: int
    page_size: int
    total: int


class ClaimedCaseResponse(BaseModel):
    report_id: int
    report_reference: str

    owner: CaseOwnerResponse

    status_code: CaseStatus
    status_label: str

    claimed_at: datetime


class PreciseLocationResponse(BaseModel):
    latitude: float | None = None
    longitude: float | None = None

    uncertainty_metres: int | None = None
    confidence_label: str | None = None
    source_label: str | None = None

    relocation_notes: str | None = None


class EvidenceSummary(BaseModel):
    evidence_id: int
    media_type: str

    captured_at: datetime | None = None
    uploaded_at: datetime


class CoordinatorCaseResponse(BaseModel):
    report_id: int
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

    evidence: list[EvidenceSummary] = []