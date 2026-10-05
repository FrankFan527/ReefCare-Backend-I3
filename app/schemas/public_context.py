# ---------------------------------------------------------------------------
# US8.2 / US2.4 Reusable public-safe site context — contracts.
#
# One boundary that both E2 Public Reef Activity and E9 Reef-Aware Planning
# read, so the privacy rule is written once rather than re-implemented per
# consumer (AC5).
#
# The contract is shaped by what must NOT appear. No report reference, no
# Observer identity, no description, no evidence, no precise coordinate, no
# Coordinator identity or note, no private closure detail (AC3). Nothing in
# this module has a field for any of them.
#
# Two further rules shape the wording:
#
#   AC4  no eligible information returns an explicit no-public-context state
#   AC6  low activity is never presented as safety, absence of threats or
#        current reef condition
# ---------------------------------------------------------------------------

from datetime import date
from enum import Enum

from pydantic import Field

from app.schemas.common import APIModel


class PublicContextState(str, Enum):
    AVAILABLE = "available"
    NO_PUBLIC_CONTEXT = "no_public_context"


class PublicThreatSummary(APIModel):
    """
    One threat category with how often it has been reported and accepted at
    this site, and how recently.

    recentMonth is month precision on purpose. An exact date at a quiet site
    could identify a single dive and, through it, a single diver.
    """

    threat_category_code: str
    threat_category_label: str

    accepted_report_count: int

    most_recent_month: str | None = None


class PublicActivityEntry(APIModel):
    """
    Conservation or monitoring activity that has been approved for publication.

    Two sources feed this: curated public activity records, and E7 follow-up
    records a Coordinator has marked publishable.
    """

    # the curated record's own id, so the Iteration 2 /activity contract
    # keeps the stable identifier it already publishes. A follow-up record
    # has none: it is identified by its case, which is not public.
    activity_id: int | None = None

    activity_type: str
    title: str
    summary: str

    activity_date: date | None = None
    source_label: str | None = None


class PublicAssessmentSummary(APIModel):
    """
    AC2 permits a clear assessment-status grouping.

    Only two numbers are published: observations whose evidence a Coordinator
    accepted, and observations still being reviewed. The second is a bare
    count with no categories, because an unreviewed report is not a finding
    and should not read as one.
    """

    accepted_observations: int = 0
    observations_under_review: int = 0


class PublicSiteContextResponse(APIModel):
    dive_site_id: int
    site_name: str
    public_area_label: str

    state: PublicContextState

    # shown as-is for both states
    message: str

    assessment_summary: PublicAssessmentSummary = Field(
        default_factory=PublicAssessmentSummary
    )

    threats: list[PublicThreatSummary] = Field(default_factory=list)

    activity: list[PublicActivityEntry] = Field(default_factory=list)

    # AC6: travels with every response, including the available one, because
    # the misreading this prevents is likelier when there is little to show
    interpretation_note: str = (
        "This summary reflects what has been reported to ReefCare and reviewed "
        "by a coordinator. It is not a survey of the site, and it is not "
        "evidence that a site is safe, unaffected or free of reef threats."
    )
