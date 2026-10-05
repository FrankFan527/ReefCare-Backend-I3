# ---------------------------------------------------------------------------
# US8.2 / US2.4 Reusable public-safe site context — policy.
#
# This is the single public-safe boundary for ReefCare information about a
# site (AC5). E2 Public Reef Activity and E9 Reef-Aware Planning both read it
# rather than each writing their own privacy rule.
#
# Two things this service will not do, in any state:
#
#   it will not describe a site as safe, unaffected or free of threats (AC6).
#   The interpretation note travels with every response, including the
#   available one, because the misreading is likeliest where there is little
#   to show.
#
#   it will not publish a report that was reviewed and not substantiated.
#   Broadcasting a rejected claim about a named site would be worse than
#   publishing nothing.
# ---------------------------------------------------------------------------

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import public_context_repository as the_repository
from app.schemas.public_context import (
    PublicActivityEntry,
    PublicAssessmentSummary,
    PublicContextState,
    PublicSiteContextResponse,
    PublicThreatSummary,
)


# How many accepted observations a threat category needs before it is named
# publicly.
#
# Set to 1 for Iteration 3, which publishes a category as soon as one
# observation has been accepted. The alternative is 2, which protects the
# single reporter at a quiet site from being identifiable by anyone who knows
# who dived there, at the cost of publishing almost nothing for most sites.
#
# This is the open E8 eligibility decision with HongShen. It is one constant
# so the team can change the rule without touching a query.
THE_MINIMUM_ACCEPTED_REPORTS_PER_CATEGORY: int = 1


THE_NO_CONTEXT_MESSAGE: str = (
    "No reviewed ReefCare information is currently available for this site. "
    "This means nothing has been reported and accepted here yet, which is "
    "not a statement about the condition of the reef."
)


def build_available_message(
    the_threat_count: int,
    the_activity_count: int,
) -> str:
    the_parts: list[str] = []

    if the_threat_count:
        the_parts.append(
            f"{the_threat_count} reviewed threat "
            f"{'category' if the_threat_count == 1 else 'categories'}"
        )

    if the_activity_count:
        the_parts.append(
            f"{the_activity_count} published conservation "
            f"{'activity record' if the_activity_count == 1 else 'activity records'}"
        )

    return (
        "ReefCare information for this site covers "
        + " and ".join(the_parts)
        + "."
    )


def to_threat_summary(
    the_row: dict,
) -> PublicThreatSummary:
    return PublicThreatSummary(
        threat_category_code=the_row["threat_category_code"],
        threat_category_label=the_row["threat_category_label"],
        accepted_report_count=the_row["accepted_report_count"],
        most_recent_month=the_row["most_recent_month"],
    )


def to_activity_entry(
    the_row: dict,
) -> PublicActivityEntry:
    return PublicActivityEntry(
        activity_id=the_row.get("activity_id"),
        activity_type=the_row["activity_type"],
        title=the_row["title"],
        summary=the_row["summary"],
        activity_date=the_row["activity_date"],
        source_label=the_row["source_label"],
    )


async def get_public_site_context(
    db: AsyncSession,
    dive_site_id: int,
) -> PublicSiteContextResponse:
    """
    The public-safe ReefCare context for one configured site.

    Returns no_public_context when nothing meets the eligibility rule, which
    is a statement about ReefCare's coverage and never about the reef (AC4).
    """

    the_site = await the_repository.get_public_site_identity(
        db=db,
        dive_site_id=dive_site_id,
    )

    if the_site is None:
        raise NotFoundError("Dive site not found")

    the_threat_rows = await the_repository.summarise_accepted_threats(
        db=db,
        dive_site_id=dive_site_id,
    )

    the_threats = [
        to_threat_summary(the_row)
        for the_row in the_threat_rows
        if the_row["accepted_report_count"] >= THE_MINIMUM_ACCEPTED_REPORTS_PER_CATEGORY
    ]

    the_activity_rows = await the_repository.list_publishable_activity(
        db=db,
        dive_site_id=dive_site_id,
    )

    the_activity = [to_activity_entry(the_row) for the_row in the_activity_rows]

    the_counts = await the_repository.count_observations_by_assessment(
        db=db,
        dive_site_id=dive_site_id,
    )

    the_summary = PublicAssessmentSummary(
        accepted_observations=the_counts["accepted_observations"],
        observations_under_review=the_counts["observations_under_review"],
    )

    the_has_context = bool(the_threats or the_activity)

    return PublicSiteContextResponse(
        dive_site_id=the_site["dive_site_id"],
        site_name=the_site["site_name"],
        public_area_label=the_site["public_area_label"],
        state=(
            PublicContextState.AVAILABLE
            if the_has_context
            else PublicContextState.NO_PUBLIC_CONTEXT
        ),
        message=(
            build_available_message(len(the_threats), len(the_activity))
            if the_has_context
            else THE_NO_CONTEXT_MESSAGE
        ),
        # the counts are returned in both states: an honest "3 reports are
        # being reviewed" is more useful, and less misleading, than silence
        assessment_summary=the_summary,
        threats=the_threats,
        activity=the_activity,
    )


async def list_publishable_activity_entries(
    db: AsyncSession,
    dive_site_id: int,
    include_follow_ups: bool = True,
) -> list[PublicActivityEntry]:
    """
    The publishable activity for one site, as the existing E2 /activity
    endpoint needs it.

    Exposed so that endpoint can converge on this service rather than keep a
    second copy of the eligibility rule (AC5, backend doc 6.8).
    """

    the_rows = await the_repository.list_publishable_activity(
        db=db,
        dive_site_id=dive_site_id,
        include_follow_ups=include_follow_ups,
    )

    return [to_activity_entry(the_row) for the_row in the_rows]
