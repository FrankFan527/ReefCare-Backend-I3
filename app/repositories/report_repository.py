from datetime import date
from typing import Any

from sqlalchemy import (
    bindparam,
    text,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)


# ---------------------------------------------------------------------------
# Report submission.
#
# PostgreSQL reefcare_submit_report() is the authoritative write path for a
# completed report. Python validates the request and reference data first,
# then passes the canonical values into this function.
# ---------------------------------------------------------------------------

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
    evidence: list[
        dict[str, Any]
    ],
    estimated_depth_metres: (
        float | None
    ) = None,
    latitude: (
        float | None
    ) = None,
    longitude: (
        float | None
    ) = None,
    relocation_notes: (
        str | None
    ) = None,
) -> str:
    """
    Submit a complete report through the canonical
    PostgreSQL reefcare_submit_report() function.
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
    Return the immediate confirmation projection for the
    submitting Observer.

    This keeps the established Iteration 1 contract:
    report reference, current status, timestamp and general
    location.
    """

    result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                cs.code
                    AS status,

                r.submitted_at,

                COALESCE(
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

            WHERE
                r.report_reference =
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
    """
    Return a dive session only when it belongs to the
    authenticated Observer.

    The ownership condition is applied in SQL so a session
    belonging to another user is never loaded into the
    service layer.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ds.dive_session_id,
                ds.dive_site_id,
                ds.observer_id

            FROM dive_session ds

            WHERE
                ds.dive_session_id =
                    :dive_session_id

                AND ds.observer_id =
                    :observer_id

            LIMIT 1
            """
        ),
        {
            "dive_session_id":
                dive_session_id,

            "observer_id":
                observer_id,
        },
    )

    return result.mappings().first()


# ---------------------------------------------------------------------------
# Observer report tracking (US6.1 / US6.2).
#
# reefcare_my_reports(observer_id) remains the primary ownership boundary.
# The extra joins below only enrich rows that have already been scoped to the
# authenticated Observer.
#
# No coordinator identity, internal decision field or private evidence object
# reference is selected.
# ---------------------------------------------------------------------------


async def list_my_reports(
    db: AsyncSession,
    *,
    observer_id: int,
    status_code: (
        str | None
    ) = None,
    from_date: (
        date | None
    ) = None,
    to_date: (
        date | None
    ) = None,
    page: int = 1,
    page_size: int = 20,
):
    """
    Return one Observer's reports with richer Iteration 2
    tracking information.

    reefcare_my_reports() already provides:
    - ownership scope
    - threat label
    - general location
    - Observer-safe status label
    - Observer-safe closure label
    - submitted timestamp

    This query enriches those safe rows with:
    - canonical status code
    - observed timestamp
    - dive-site name
    - last workflow update timestamp
    """

    offset = (
        (page - 1)
        * page_size
    )

    filter_sql = """
        WHERE (
            CAST(:status_code AS text) IS NULL
            OR cs.code =
               CAST(:status_code AS text)
        )

        AND (
            CAST(:from_date AS date) IS NULL
            OR m.submitted_at >=
               CAST(:from_date AS date)
        )

        AND (
            CAST(:to_date AS date) IS NULL
            OR m.submitted_at <
               CAST(:to_date AS date)
               + INTERVAL '1 day'
        )
    """

    result = await db.execute(
        text(
            f"""
            WITH mine AS (
                SELECT *

                FROM reefcare_my_reports(
                    CAST(
                        :observer_id
                        AS bigint
                    )
                )
            )

            SELECT
                m.report_reference,
                m.threat,
                m.area,

                r.observed_at,

                ds.name
                    AS dive_site_name,

                cs.code
                    AS status,

                m.status_label,
                m.closure_label,

                m.submitted_at,

                COALESCE(
                    latest_event.occurred_at,
                    m.submitted_at
                ) AS last_updated_at

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at IS NULL

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            LEFT JOIN dive_session dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            LEFT JOIN LATERAL (
                SELECT
                    e.occurred_at

                FROM case_event e

                WHERE
                    e.report_id =
                        r.report_id

                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC

                LIMIT 1
            ) latest_event
                ON TRUE

            {filter_sql}

            ORDER BY
                m.submitted_at DESC,
                m.report_reference DESC

            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            "observer_id":
                observer_id,

            "status_code":
                status_code,

            "from_date":
                from_date,

            "to_date":
                to_date,

            "limit":
                page_size,

            "offset":
                offset,
        },
    )

    rows = (
        result.mappings().all()
    )

    count_result = await db.execute(
        text(
            f"""
            WITH mine AS (
                SELECT *

                FROM reefcare_my_reports(
                    CAST(
                        :observer_id
                        AS bigint
                    )
                )
            )

            SELECT COUNT(*)

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at IS NULL

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            {filter_sql}
            """
        ),
        {
            "observer_id":
                observer_id,

            "status_code":
                status_code,

            "from_date":
                from_date,

            "to_date":
                to_date,
        },
    )

    total = (
        count_result.scalar_one()
    )

    return (
        rows,
        total,
    )


async def get_my_report(
    db: AsyncSession,
    *,
    observer_id: int,
    report_reference: str,
):
    """
    Return one Observer-owned report with the richer
    Iteration 2 tracking projection.

    The query begins from reefcare_my_reports(observer_id),
    so another Observer's report is never part of the input
    relation.

    Only Observer-safe data is selected.
    """

    result = await db.execute(
        text(
            """
            WITH mine AS (
                SELECT *

                FROM reefcare_my_reports(
                    CAST(
                        :observer_id
                        AS bigint
                    )
                )

                WHERE
                    report_reference =
                        :report_reference
            )

            SELECT
                m.report_reference,
                m.threat,
                m.area,

                cs.code
                    AS status,

                m.status_label,
                m.closure_label,

                r.observed_at,
                r.estimated_depth_metres,
                r.description,
                r.submitted_at,

                ds.name
                    AS dive_site_name,

                (
                    SELECT COUNT(*)

                    FROM evidence ev

                    WHERE
                        ev.report_id =
                            r.report_id
                ) AS evidence_count,

                COALESCE(
                    latest_event.occurred_at,
                    r.submitted_at
                ) AS last_updated_at,

                CASE
                    WHEN
                        cs.code =
                        'needs_more_info'

                    THEN
                        info_event.note

                    ELSE NULL
                END AS
                    information_request_reason,

                CASE
                    WHEN
                        cs.is_terminal

                    THEN
                        close_event.note

                    ELSE NULL
                END AS
                    public_closure_note

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at IS NULL

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            LEFT JOIN dive_session dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            LEFT JOIN LATERAL (
                SELECT
                    e.note

                FROM case_event e

                WHERE
                    e.report_id =
                        r.report_id

                    AND e.event_type =
                        'info_requested'

                    AND e.note IS NOT NULL

                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC

                LIMIT 1
            ) info_event
                ON TRUE

            LEFT JOIN LATERAL (
                SELECT
                    e.note

                FROM case_event e

                JOIN case_status terminal_status
                    ON
                        terminal_status
                        .case_status_id =
                        e.to_status_id

                WHERE
                    e.report_id =
                        r.report_id

                    AND
                        terminal_status
                        .is_terminal = TRUE

                    AND e.note IS NOT NULL

                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC

                LIMIT 1
            ) close_event
                ON TRUE

            LEFT JOIN LATERAL (
                SELECT
                    e.occurred_at

                FROM case_event e

                WHERE
                    e.report_id =
                        r.report_id

                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC

                LIMIT 1
            ) latest_event
                ON TRUE

            LIMIT 1
            """
        ),
        {
            "observer_id":
                observer_id,

            "report_reference":
                report_reference,
        },
    )

    return (
        result.mappings().first()
    )


async def get_report_timeline(
    db: AsyncSession,
    *,
    observer_id: int,
    report_reference: str,
):
    """
    Return deterministic Observer-facing status history.

    reefcare_report_timeline() exposes only:
    - case_status.observer_label
    - occurred_at

    It does not expose:
    - actor identity
    - coordinator identity
    - notes
    - internal event type
    - raw decision data
    """

    result = await db.execute(
        text(
            """
            SELECT
                status_label,
                occurred_at

            FROM reefcare_report_timeline(
                CAST(
                    :report_reference
                    AS text
                ),

                CAST(
                    :observer_id
                    AS bigint
                )
            )
            """
        ),
        {
            "observer_id":
                observer_id,

            "report_reference":
                report_reference,
        },
    )

    return result.mappings().all()


# ---------------------------------------------------------------------------
# Iteration 3 — E4 AI suggestion persistence.
#
# Smart Report Structuring and Visual Threat Recognition are independent
# advisory sources.
#
# The database uniqueness boundary is:
#
#     UNIQUE(report_id, field, source)
#
# This allows both AI systems to suggest a value for the same report field
# without losing provenance.
# ---------------------------------------------------------------------------


async def save_reviewed_ai_suggestions(
    db: AsyncSession,
    report_reference: str,
    suggestions: list,
) -> int:
    """
    Persist the Observer's final decision about each AI
    suggestion.

    Iteration 3 supports two independent advisory sources:

    - smart_report
    - visual_recognition

    A report may therefore contain two suggestions for the
    same field, one from each source.

    The database uniqueness contract is:

        UNIQUE (
            report_id,
            field,
            source
        )

    This function is called inside the existing report
    submission transaction after reefcare_submit_report()
    and before commit.

    Only resolved suggestions should reach this function.
    The API/service layer rejects unresolved suggestions
    before persistence, and the database status constraint
    provides an additional final guard.

    'removed' suggestions are still persisted because they
    are a truthful record of what the AI proposed and what
    the Observer chose to reject.

    The caller owns the transaction and commits.
    """

    if not suggestions:
        return 0

    inserted = 0

    for suggestion in suggestions:
        result = await db.execute(
            text(
                """
                INSERT INTO report_ai_suggestion
                    (
                        report_id,
                        field,
                        suggested_value,
                        status,
                        source,
                        confidence
                    )

                SELECT
                    r.report_id,
                    :field,
                    :suggested_value,
                    :status,
                    :source,
                    :confidence

                FROM report AS r

                WHERE
                    r.report_reference =
                        :report_reference

                    AND r.deleted_at IS NULL

                RETURNING
                    report_ai_suggestion_id
                """
            ),
            {
                "report_reference":
                    report_reference,

                "field":
                    suggestion.field,

                "suggested_value":
                    suggestion.suggested_value,

                "status":
                    suggestion.status,

                "source":
                    suggestion.source,

                "confidence":
                    suggestion.confidence,
            },
        )

        inserted_id = (
            result.scalar_one_or_none()
        )

        if inserted_id is not None:
            inserted += 1

    return inserted


async def get_reviewed_ai_suggestions(
    db: AsyncSession,
    report_reference: str,
) -> list:
    """
    Return Observer-reviewed AI suggestions for one report.

    Only confirmed and corrected suggestions are exposed to
    the Coordinator review projection.

    Removed suggestions remain stored for provenance but are
    deliberately not presented as describing the submitted
    report.

    Iteration 3 also returns source and confidence so Smart
    Report Structuring and Visual Recognition can be
    distinguished after submission.

    Ordering by field and source keeps the response stable
    when both AI systems suggested a value for the same
    field.
    """

    result = await db.execute(
        text(
            """
            SELECT
                s.field,
                s.source,
                s.suggested_value,
                s.confidence,
                s.status

            FROM report_ai_suggestion AS s

            JOIN report AS r
                ON r.report_id =
                    s.report_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL

                AND s.status IN (
                    'confirmed',
                    'corrected'
                )

            ORDER BY
                s.field,
                s.source,
                s.report_ai_suggestion_id
            """
        ),
        {
            "report_reference":
                report_reference,
        },
    )

    return result.mappings().all()


# ---------------------------------------------------------------------------
# Iteration 3 — E6 Observer Impact Feedback.
#
# These queries are deliberately read-only.
#
# They expose only information that may be projected back
# to the Observer. They never return:
#
# - another Observer's identity
# - coordinator identity
# - another report reference
# - internal incident ids
# - private evidence
# - internal relationship notes
#
# Ownership is enforced in SQL with report.observer_id.
# ---------------------------------------------------------------------------


async def get_observer_related_incident_event(
    db: AsyncSession,
    observer_id: int,
    report_reference: str,
) -> dict | None:
    """
    Return the latest human-confirmed same-incident event
    involving one Observer-owned report.

    The related report itself is deliberately not returned.

    US6.2 only needs to tell the Observer that their report
    was linked to an existing report of the same issue.
    """

    result = await db.execute(
        text(
            """
            SELECT
                d.decided_at
                    AS occurred_at

            FROM report AS r

            JOIN report_relationship_decision AS d
                ON (
                    d.report_id = r.report_id
                    OR
                    d.related_report_id = r.report_id
                )

            WHERE
                r.report_reference =
                    :report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at
                    IS NULL

                AND d.decision =
                    'same_incident'

            ORDER BY
                d.decided_at DESC,
                d.report_relationship_decision_id DESC

            LIMIT 1
            """
        ),
        {
            "observer_id":
                observer_id,

            "report_reference":
                report_reference,
        },
    )

    row = (
        result
        .mappings()
        .first()
    )

    if row is None:
        return None

    return dict(row)


async def get_observer_contribution(
    db: AsyncSession,
    observer_id: int,
    report_reference: str,
) -> dict | None:
    """
    Return the latest valid E7 action/follow-up state for
    one Observer-owned report.

    E6 is private feedback to the submitting Observer.
    Therefore it must not depend on
    case_action.is_publishable.

    is_publishable is reserved for the E8 public-activity
    publication boundary.

    The projection deliberately excludes:
    - created_by
    - responsible_team
    - internal notes
    - source_reference
    - evidence references
    - reviewer identity

    Only the latest currently valid follow-up is returned.

    Records are excluded when:
    - they are demonstration records
    - they have been superseded by a later correction

    A planned action therefore remains planned, while an
    action_taken record may be described as completed.

    The service layer remains responsible for converting
    the returned record into an Observer-safe summary.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ca.case_action_id,

                at.code
                    AS action_type_code,

                at.label
                    AS action_type_label,

                ca.action_state,

                ca.action_date,

                ca.follow_up_type,

                ca.recording_level,

                ca.recorded_outcome,

                ca.next_follow_up_required,

                ca.next_follow_up_date,

                ca.created_at

            FROM case_action AS ca

            JOIN report AS r
                ON r.report_id =
                   ca.report_id

            JOIN action_type AS at
                ON at.action_type_id =
                   ca.action_type_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at
                    IS NULL

                AND COALESCE(
                    ca.is_demonstration,
                    FALSE
                ) IS FALSE

                AND NOT EXISTS (
                    SELECT 1

                    FROM case_action AS later

                    WHERE
                        later.supersedes_case_action_id =
                            ca.case_action_id
                )

            ORDER BY
                ca.created_at DESC,
                ca.case_action_id DESC

            LIMIT 1
            """
        ),
        {
            "observer_id":
                observer_id,

            "report_reference":
                report_reference,
        },
    )

    row = (
        result
        .mappings()
        .first()
    )

    if row is None:
        return None

    return dict(row)