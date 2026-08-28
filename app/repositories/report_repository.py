from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession


_submit_report_statement = text(
    """
    SELECT reefcare_submit_report(
        p_observer_id =>
            CAST(:observer_id AS bigint),

        p_dive_session_id =>
            CAST(:dive_session_id AS bigint),

        p_threat_category_code =>
            CAST(:threat_category_code AS text),

        p_description =>
            CAST(:description AS text),

        p_observed_at =>
            CAST(:observed_at AS timestamptz),

        p_location_source_code =>
            CAST(:location_source_code AS text),

        p_location_confidence_code =>
            CAST(:location_confidence_code AS text),

        p_evidence =>
            CAST(:evidence AS jsonb),

        p_estimated_depth_metres =>
            CAST(:estimated_depth_metres AS numeric),

        p_latitude =>
            CAST(:latitude AS numeric),

        p_longitude =>
            CAST(:longitude AS numeric),

        p_relocation_notes =>
            CAST(:relocation_notes AS text)
    ) AS report_reference
    """
).bindparams(
    bindparam(
        "evidence",
        type_=JSONB,
    )
)


async def submit_report(
    db: AsyncSession,
    *,
    observer_id: int,
    dive_session_id: int,
    threat_category_code: str,
    description: str,
    observed_at,
    location_source_code: str,
    location_confidence_code: str,
    evidence: list[dict[str, Any]],
    estimated_depth_metres: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    relocation_notes: str | None = None,
) -> str:
    """
    Submit a complete report through the canonical
    PostgreSQL reefcare_submit_report() function.

    PostgreSQL atomically creates:
    - report_location
    - report
    - evidence rows
    - submitted case_event
    - automatic received status event

    This repository does not commit the transaction.
    Transaction ownership belongs to the service layer.
    """

    result = await db.execute(
        _submit_report_statement,
        {
            "observer_id":
                observer_id,

            "dive_session_id":
                dive_session_id,

            "threat_category_code":
                threat_category_code,

            "description":
                description,

            "observed_at":
                observed_at,

            "location_source_code":
                location_source_code,

            "location_confidence_code":
                location_confidence_code,

            "evidence":
                evidence,

            "estimated_depth_metres":
                estimated_depth_metres,

            "latitude":
                latitude,

            "longitude":
                longitude,

            "relocation_notes":
                relocation_notes,
        },
    )

    return result.scalar_one()

async def get_submission_confirmation(
    db: AsyncSession,
    *,
    report_reference: str,
    observer_id: int,
):
    """
    Return the post-submission data required by the
    ReportSubmittedResponse.

    The observer_id condition prevents this helper from
    returning another observer's report.
    """

    result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                cs.code AS status,

                r.submitted_at,

                COALESCE(
                    ds.name,
                    ds.public_area_label,
                    'Location not specified'
                ) AS general_location

            FROM report r

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            LEFT JOIN dive_session dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            WHERE r.report_reference =
                  :report_reference

              AND r.observer_id =
                  :observer_id

              AND r.deleted_at IS NULL

            LIMIT 1
            """
        ),
        {
            "report_reference":
                report_reference,

            "observer_id":
                observer_id,
        },
    )

    return result.mappings().first()

async def get_owned_dive_session(
    db: AsyncSession,
    *,
    dive_session_id: int,
    observer_id: int,
):
    result = await db.execute(
        text(
            """
            SELECT
                ds.dive_session_id,
                ds.dive_site_id,
                ds.observer_id
            FROM dive_session ds
            WHERE ds.dive_session_id = :dive_session_id
              AND ds.observer_id = :observer_id
            LIMIT 1
            """
        ),
        {
            "dive_session_id": dive_session_id,
            "observer_id": observer_id,
        },
    )

    return result.mappings().first()

