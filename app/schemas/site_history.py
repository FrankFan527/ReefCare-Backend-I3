# ---------------------------------------------------------------------------
# US8.1 Coordinator site history — contracts.
#
# A chronological projection over eligible reports at one site and the E7
# follow-up records on those reports. Nothing is copied into a new table:
# the canonical rows stay the source of truth (backend doc Appendix B).
#
# The contract is built around two rules that are easy to get wrong:
#
#   AC3  an observation still under review must never read like an accepted
#        one, so every observation carries an explicit assessment state
#
#   AC5  an empty history is stated as insufficient history, never as a site
#        with no threats and no conservation activity
# ---------------------------------------------------------------------------

from datetime import date, datetime
from enum import Enum

from pydantic import Field

from app.schemas.common import APIModel


class SiteHistoryRecordType(str, Enum):
    """
    US8.1 AC4. An observation, an action and a monitoring visit are different
    kinds of event and are never flattened into one.
    """

    OBSERVATION = "observation"
    ACTION = "action"
    MONITORING = "monitoring"
    SOURCED_OUTCOME = "sourced_outcome"


class AssessmentState(str, Enum):
    """
    US8.1 AC3. Where an observation has reached in review.

    Derived from the recorded decision where one exists, and from the case
    status otherwise. A closed case is not treated as an accepted one:
    closure and acceptance are different things.
    """

    NOT_YET_ASSESSED = "not_yet_assessed"
    UNDER_REVIEW = "under_review"
    EVIDENCE_ACCEPTED = "evidence_accepted"
    NOT_SUBSTANTIATED = "not_substantiated"
    CLOSED_WITHOUT_ASSESSMENT = "closed_without_assessment"


class SiteHistoryState(str, Enum):
    AVAILABLE = "available"
    INSUFFICIENT_HISTORY = "insufficient_history"


# plain-language labels, so the UI never has to invent wording for a state
THE_ASSESSMENT_STATE_LABELS: dict[AssessmentState, str] = {
    AssessmentState.NOT_YET_ASSESSED:
        "Reported, not yet reviewed",
    AssessmentState.UNDER_REVIEW:
        "Under review",
    AssessmentState.EVIDENCE_ACCEPTED:
        "Evidence accepted",
    AssessmentState.NOT_SUBSTANTIATED:
        "Could not be confirmed from the evidence provided",
    AssessmentState.CLOSED_WITHOUT_ASSESSMENT:
        "Closed without a recorded evidence assessment",
}


class SiteHistoryItem(APIModel):
    """
    One dated event in the site's history.

    reportReference is present only for reports the requesting Coordinator
    owns (US1.3 AC2). For every other report the item still appears, with its
    threat category and assessment state, because a site history that hides
    other Coordinators' work would misrepresent the site.

    Descriptions, evidence, observer identity and coordinates never appear
    here for any report, owned or not.
    """

    record_type: SiteHistoryRecordType

    occurred_at: datetime | None = None
    occurred_on: date | None = None

    # observations
    threat_category_code: str | None = None
    threat_category_label: str | None = None

    assessment_state: AssessmentState | None = None
    assessment_state_label: str | None = None

    # follow-up records
    follow_up_type: str | None = None
    follow_up_state: str | None = None

    condition_code: str | None = None
    condition_label: str | None = None

    responsible_team: str | None = None
    recorded_outcome: str | None = None

    next_follow_up_required: bool | None = None
    next_follow_up_date: date | None = None

    # ownership, so the UI can show what this Coordinator may open
    report_reference: str | None = None
    owned_by_you: bool = False

    recorded_at: datetime


class SiteHistoryCounts(APIModel):
    observations: int = 0
    actions: int = 0
    monitoring_visits: int = 0
    sourced_outcomes: int = 0

    observations_by_assessment_state: dict[str, int] = Field(default_factory=dict)


class SiteHistoryResponse(APIModel):
    dive_site_id: int
    site_name: str
    public_area_label: str

    state: SiteHistoryState

    # shown as-is for both states
    message: str

    first_record_on: date | None = None
    last_record_on: date | None = None

    counts: SiteHistoryCounts = Field(default_factory=SiteHistoryCounts)

    items: list[SiteHistoryItem] = Field(default_factory=list)

    # US8.1 AC6: E8 is site-scoped, and broader patterns stay with E5
    hotspot_note: str = (
        "This is the recorded history for one site. "
        "Use Geospatial Hotspot Analysis for patterns across areas and time."
    )
