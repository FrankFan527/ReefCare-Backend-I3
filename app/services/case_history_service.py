# ---------------------------------------------------------------------------
# Closed case and referral history policy (US5.8 / API-10).
# ---------------------------------------------------------------------------

from datetime import datetime

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.exceptions import (
    DomainValidationError,
)
from app.repositories.case_history_repository import (
    closure_reason_code_exists,
    list_closed_cases,
    list_referral_history,
    threat_code_exists,
)


async def validate_filter_values(
    db: AsyncSession,
    closure_reason_code: (
        str | None
    ),
    threat_code: (
        str | None
    ),
) -> None:
    """
    Reject filter codes that do not exist in canonical
    reference data.

    This prevents a misspelled filter from looking like a
    legitimate empty history.
    """

    if (
        closure_reason_code
        is not None
    ):
        reason_exists = (
            await closure_reason_code_exists(
                db=db,
                closure_reason_code=(
                    closure_reason_code
                ),
            )
        )

        if not reason_exists:
            raise DomainValidationError(
                "Unknown closure reason: "
                f"{closure_reason_code}"
            )

    if (
        threat_code
        is not None
    ):
        threat_exists = (
            await threat_code_exists(
                db=db,
                threat_code=(
                    threat_code
                ),
            )
        )

        if not threat_exists:
            raise DomainValidationError(
                "Unknown threat category: "
                f"{threat_code}"
            )


def validate_date_window(
    closed_from: (
        datetime | None
    ),
    closed_to: (
        datetime | None
    ),
) -> None:
    """
    Reject an empty or inverted closed-case date window.
    """

    if (
        closed_from is not None
        and closed_to is not None
        and closed_from >= closed_to
    ):
        raise DomainValidationError(
            "closedFrom must be earlier "
            "than closedTo"
        )


def group_referrals_by_report(
    referral_rows: list[
        dict
    ],
) -> dict[
    str,
    list[dict],
]:
    """
    Group one flat referral query by report reference.
    """

    grouped: dict[
        str,
        list[dict],
    ] = {}

    for row in referral_rows:
        grouped.setdefault(
            row[
                "report_reference"
            ],
            [],
        ).append(
            row
        )

    return grouped


async def get_closed_case_history(
    db: AsyncSession,
    coordinator_id: int,
    closure_reason_code: (
        str | None
    ) = None,
    threat_code: (
        str | None
    ) = None,
    closed_from: (
        datetime | None
    ) = None,
    closed_to: (
        datetime | None
    ) = None,
    was_referred: (
        bool | None
    ) = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Return the authenticated coordinator's own filtered
    closed-case history.

    Ownership is enforced in SQL.

    Referral details are loaded once for the entire page,
    rather than one query per case.
    """

    validate_date_window(
        closed_from=closed_from,
        closed_to=closed_to,
    )

    await validate_filter_values(
        db=db,
        closure_reason_code=(
            closure_reason_code
        ),
        threat_code=threat_code,
    )

    (
        rows,
        total,
    ) = await list_closed_cases(
        db=db,
        coordinator_id=(
            coordinator_id
        ),
        closure_reason_code=(
            closure_reason_code
        ),
        threat_code=threat_code,
        closed_from=closed_from,
        closed_to=closed_to,
        was_referred=(
            was_referred
        ),
        page=page,
        page_size=page_size,
    )

    references = [
        row["report_reference"]
        for row in rows
    ]

    referral_rows = (
        await list_referral_history(
            db=db,
            report_references=(
                references
            ),
            coordinator_id=(
                coordinator_id
            ),
        )
    )

    referrals_by_report = (
        group_referrals_by_report(
            referral_rows=(
                referral_rows
            ),
        )
    )

    items = []

    for row in rows:
        referrals = (
            referrals_by_report.get(
                row[
                    "report_reference"
                ],
                [],
            )
        )

        items.append(
            {
                "report_reference":
                    row[
                        "report_reference"
                    ],

                "threat_code":
                    row[
                        "threat_code"
                    ],

                "threat":
                    row["threat"],

                "area":
                    row["area"],

                "status_code":
                    row[
                        "status_code"
                    ],

                "status_label":
                    row[
                        "status_label"
                    ],

                "submitted_at":
                    row[
                        "submitted_at"
                    ],

                "closed_at":
                    row[
                        "closed_at"
                    ],

                "closure_reason_code":
                    row[
                        "closure_reason_code"
                    ],

                "closure_reason_label":
                    row[
                        "closure_reason_label"
                    ],

                "closure_note":
                    row[
                        "closure_note"
                    ],

                "was_referred":
                    bool(
                        referrals
                    ),

                "referrals":
                    referrals,
            }
        )

    return {
        "items":
            items,

        "page":
            page,

        "page_size":
            page_size,

        "total":
            total,

        "applied_filters": {
            "closure_reason":
                closure_reason_code,

            "threat_category":
                threat_code,

            "closed_from":
                closed_from,

            "closed_to":
                closed_to,

            "was_referred":
                was_referred,
        },
    }