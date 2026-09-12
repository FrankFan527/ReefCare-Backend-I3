# ---------------------------------------------------------------------------
# Closed case and referral history policy (US5.8).
#
# Services decide what may be asked for; repositories answer it.
#
# There is no ownership check in this module, and that is deliberate rather
# than an omission. Every other coordinator service loads one case and then
# checks it belongs to the caller. A history query has no single case to check,
# so ownership is expressed as part of the query instead: both repository
# functions filter on r.claimed_by_user_id = :coordinator_id. A case the
# coordinator does not own is not excluded after the fact, it is never
# selected.
#
# US5.8 AC1 says "the Coordinator's authorised closed-case history", which is
# why there is no owner filter in the API. The endpoint is already scoped to
# the caller, so a coordinator parameter could only either do nothing or
# widen access.
# ---------------------------------------------------------------------------

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DomainValidationError
from app.repositories.case_history_repository import (
    closure_reason_code_exists,
    list_closed_cases,
    list_referral_history,
    threat_code_exists,
)


async def validate_filter_values(
    db: AsyncSession,
    closure_reason_code: str | None,
    threat_code: str | None,
) -> None:
    """
    Reject filter codes that do not exist.

    An empty result set is a legitimate answer and a misspelled filter is not,
    but they look identical to the caller. Failing loudly here means a
    coordinator who types the wrong code learns that, instead of concluding
    they have no closed cases.

    Validated against the reference tables rather than a hardcoded list, so a
    closure reason added to the database becomes filterable with no code
    change.
    """

    if closure_reason_code is not None:
        if not await closure_reason_code_exists(
            db=db,
            closure_reason_code=closure_reason_code,
        ):
            raise DomainValidationError(
                f"Unknown closure reason: {closure_reason_code}"
            )

    if threat_code is not None:
        if not await threat_code_exists(
            db=db,
            threat_code=threat_code,
        ):
            raise DomainValidationError(
                f"Unknown threat category: {threat_code}"
            )


def validate_date_window(
    closed_from: datetime | None,
    closed_to: datetime | None,
) -> None:
    """
    Reject a window that cannot contain anything.

    A backwards range returns an empty page that reads as "no closed cases",
    which is a different and much more alarming statement than "your dates are
    the wrong way round".
    """

    if (
        closed_from is not None
        and closed_to is not None
        and closed_from >= closed_to
    ):
        raise DomainValidationError(
            "closedFrom must be earlier than closedTo"
        )


def group_referrals_by_report(
    referral_rows: list[dict],
) -> dict[str, list[dict]]:
    """
    Turn one flat list of referrals into a lookup keyed by report reference.

    The repository fetches referrals for the whole page in a single query;
    this is what makes that possible without a per-row lookup.
    """

    the_grouped: dict[str, list[dict]] = {}

    for the_row in referral_rows:
        the_reference = the_row["report_reference"]

        the_grouped.setdefault(the_reference, []).append(the_row)

    return the_grouped


async def get_closed_case_history(
    db: AsyncSession,
    coordinator_id: int,
    closure_reason_code: str | None = None,
    threat_code: str | None = None,
    closed_from: datetime | None = None,
    closed_to: datetime | None = None,
    was_referred: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Return a filtered page of the coordinator's own closed cases.

    Two queries regardless of page size: one for the cases, one for every
    referral across them. Fetching referrals per row would turn a twenty-row
    page into twenty-one round trips for data that is usually empty.

    Validation runs before either query. A bad date window or an unknown code
    should cost nothing to reject.
    """

    validate_date_window(
        closed_from=closed_from,
        closed_to=closed_to,
    )

    await validate_filter_values(
        db=db,
        closure_reason_code=closure_reason_code,
        threat_code=threat_code,
    )

    the_rows, the_total = await list_closed_cases(
        db=db,
        coordinator_id=coordinator_id,
        closure_reason_code=closure_reason_code,
        threat_code=threat_code,
        closed_from=closed_from,
        closed_to=closed_to,
        was_referred=was_referred,
        page=page,
        page_size=page_size,
    )

    the_references = [
        the_row["report_reference"]
        for the_row in the_rows
    ]

    the_referral_rows = await list_referral_history(
        db=db,
        report_references=the_references,
        coordinator_id=coordinator_id,
    )

    the_referrals_by_report = group_referrals_by_report(
        referral_rows=the_referral_rows,
    )

    the_items = []

    for the_row in the_rows:
        the_items.append(
            {
                "report_reference": the_row["report_reference"],
                "threat": the_row["threat"],
                "area": the_row["area"],
                "status_code": the_row["status_code"],
                "status_label": the_row["status_label"],
                "submitted_at": the_row["submitted_at"],
                "closed_at": the_row["closed_at"],
                "closure_reason_code": the_row["closure_reason_code"],
                "closure_reason_label": the_row["closure_reason_label"],
                "closure_note": the_row["closure_note"],
                "referrals": the_referrals_by_report.get(
                    the_row["report_reference"], []
                ),
            }
        )

    return {
        "items": the_items,
        "page": page,
        "page_size": page_size,
        "total": the_total,
        # Echoed back so a short page cannot be misread as an empty history.
        "filters_applied": {
            "closureReason": closure_reason_code,
            "threatCategory": threat_code,
            "closedFrom": (
                closed_from.isoformat()
                if closed_from is not None
                else None
            ),
            "closedTo": (
                closed_to.isoformat()
                if closed_to is not None
                else None
            ),
            "wasReferred": was_referred,
        },
    }