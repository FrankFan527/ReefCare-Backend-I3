# ---------------------------------------------------------------------------
# US5.9 Related Incident Detection — persistence.
#
# Repositories own SQL. This file is the only place that reads or writes the
# related_incident_* tables, incident and report_relationship_decision.
#
# Two kinds of caller:
#
#   ENGINE (HongShen, related_incident_detection_service.py)
#       get_report_comparison_facts / list_candidate_comparison_facts to read,
#       begin_detection_run / save_detection_candidates /
#       finish_detection_run to write. Nothing else.
#
#   WORKFLOW (Miusan, related_incident_service.py)
#       everything below the "WORKFLOW" banner.
#
# Human decisions go through the two SECURITY DEFINER functions only. The
# runtime role has no INSERT on incident or report_relationship_decision, so
# PostgreSQL rejects any other route.
# ---------------------------------------------------------------------------

from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.related_incident import (
    CandidateMatch,
    DetectionRunState,
)


# reports that have not reached intake are never compared
the_pre_intake_status_codes: tuple[str, ...] = (
    "draft",
    "submitted",
)


# one SELECT used by both fact readers so the engine always sees the same
# shape for the source report and for every candidate
THE_COMPARISON_FACTS_SELECT: str = """
    SELECT
        r.report_id,
        r.report_reference,
        r.observed_at,
        tc.code                         AS threat_category_code,

        ds.dive_site_id,
        ds.name                         AS dive_site_name,
        ds.public_area_label,

        -- generalised here, so the engine never holds a precise coordinate
        round(rl.latitude, 3)           AS generalised_latitude,
        round(rl.longitude, 3)          AS generalised_longitude,
        lc.code                         AS location_confidence_code,
        ls.code                         AS location_source_code,

        r.estimated_depth_metres,
        r.description

    FROM report AS r
    JOIN threat_category AS tc
        ON tc.threat_category_id = r.threat_category_id
    JOIN case_status AS cs
        ON cs.case_status_id = r.current_status_id
    LEFT JOIN dive_session AS dsn
        ON dsn.dive_session_id = r.dive_session_id
    LEFT JOIN dive_site AS ds
        ON ds.dive_site_id = dsn.dive_site_id
    LEFT JOIN report_location AS rl
        ON rl.report_location_id = r.report_location_id
    LEFT JOIN location_confidence AS lc
        ON lc.location_confidence_id = rl.location_confidence_id
    LEFT JOIN location_source AS ls
        ON ls.location_source_id = rl.location_source_id
"""


# ===========================================================================
# ENGINE — read
# ===========================================================================


async def get_report_comparison_facts(
    db: AsyncSession,
    report_reference: str,
) -> dict | None:
    """
    Facts for the report being analysed. None when the report does not exist,
    was withdrawn, or has not reached intake.
    """

    the_result = await db.execute(
        text(
            THE_COMPARISON_FACTS_SELECT
            + """
            WHERE r.report_reference = :report_reference
              AND r.deleted_at IS NULL
              AND cs.code NOT IN :pre_intake_codes
            """
        ).bindparams(
            bindparam(
                "pre_intake_codes",
                expanding=True,
            )
        ),
        {
            "report_reference":
                report_reference,

            "pre_intake_codes":
                list(
                    the_pre_intake_status_codes
                ),
        },
    )

    the_row = (
        the_result
        .mappings()
        .first()
    )

    return (
        dict(the_row)
        if the_row is not None
        else None
    )


async def list_candidate_comparison_facts(
    db: AsyncSession,
    source_report_id: int,
    observed_from: datetime,
    observed_to: datetime,
    limit: int = 200,
) -> list[dict]:
    """
    Eligible existing reports the engine may compare against.

    The engine chooses the observation window; this function only enforces
    eligibility: not the same report, not withdrawn, past intake.

    Ownership is NOT filtered here. Matching is internal, and who may see a
    candidate is decided at read time in the workflow service (AC4), because
    claims change after a run finishes.
    """

    the_bounded_limit = max(
        1,
        min(
            limit,
            500,
        ),
    )

    the_result = await db.execute(
        text(
            THE_COMPARISON_FACTS_SELECT
            + """
            WHERE r.report_id <> :source_report_id
              AND r.deleted_at IS NULL
              AND cs.code NOT IN :pre_intake_codes
              AND r.observed_at BETWEEN :observed_from AND :observed_to
            ORDER BY r.observed_at DESC, r.report_id DESC
            LIMIT :the_limit
            """
        ).bindparams(
            bindparam(
                "pre_intake_codes",
                expanding=True,
            )
        ),
        {
            "source_report_id":
                source_report_id,

            "pre_intake_codes":
                list(
                    the_pre_intake_status_codes
                ),

            "observed_from":
                observed_from,

            "observed_to":
                observed_to,

            "the_limit":
                the_bounded_limit,
        },
    )

    return [
        dict(the_row)
        for the_row
        in the_result.mappings().all()
    ]


# ===========================================================================
# ENGINE — write
# ===========================================================================


async def begin_detection_run(
    db: AsyncSession,
    report_id: int,
    rule_version: str,
    input_version: int = 1,
) -> int:
    """
    Start or restart one detection run for the same report,
    rule version and input version.

    The current database uniqueness contract is:

        UNIQUE (
            report_id,
            rule_version,
            input_version
        )

    Therefore a retry of the same analysis input reuses the
    existing run, while a later input version may create a
    separate run.

    input_version defaults to 1 for backwards compatibility
    with the existing detection service and the database
    default.

    Human relationship decisions live in a different table
    and are untouched.
    """

    the_result = await db.execute(
        text(
            """
            INSERT INTO related_incident_run
                (
                    report_id,
                    rule_version,
                    input_version,
                    run_state
                )

            VALUES
                (
                    :report_id,
                    :rule_version,
                    :input_version,
                    'processing'
                )

            ON CONFLICT
                (
                    report_id,
                    rule_version,
                    input_version
                )
            DO UPDATE
                SET
                    run_state = 'processing',
                    started_at = now(),
                    finished_at = NULL

            RETURNING
                related_incident_run_id
            """
        ),
        {
            "report_id":
                report_id,

            "rule_version":
                rule_version,

            "input_version":
                input_version,
        },
    )

    the_run_id = (
        the_result.scalar_one()
    )

    # Signals cascade from candidates.
    #
    # Re-running exactly the same report/rule/input version
    # replaces only that machine-generated candidate set.
    # Human decisions are stored separately and remain
    # untouched.
    await db.execute(
        text(
            """
            DELETE FROM related_incident_candidate
            WHERE related_incident_run_id = :run_id
            """
        ),
        {
            "run_id":
                the_run_id,
        },
    )

    return the_run_id


async def save_detection_candidates(
    db: AsyncSession,
    run_id: int,
    report_id: int,
    candidates: list[CandidateMatch],
) -> int:
    """
    Insert the engine's candidates and their signals for one run.

    Signal codes are validated against similarity_signal first, so an
    unknown code fails loudly instead of being silently dropped. The caller
    (the engine wrapper) treats any exception as a failed run.
    """

    if not candidates:
        return 0

    the_requested_codes = sorted(
        {
            the_signal.code
            for the_candidate
            in candidates
            for the_signal
            in the_candidate.signals
        }
    )

    the_signal_ids: dict[
        str,
        int,
    ] = {}

    if the_requested_codes:
        the_lookup = await db.execute(
            text(
                """
                SELECT
                    code,
                    similarity_signal_id

                FROM similarity_signal

                WHERE
                    code IN :codes
                    AND is_active
                """
            ).bindparams(
                bindparam(
                    "codes",
                    expanding=True,
                )
            ),
            {
                "codes":
                    the_requested_codes,
            },
        )

        the_signal_ids = {
            the_row["code"]:
                the_row[
                    "similarity_signal_id"
                ]

            for the_row
            in the_lookup.mappings().all()
        }

        the_unknown_codes = (
            set(
                the_requested_codes
            )
            - set(
                the_signal_ids
            )
        )

        if the_unknown_codes:
            raise ValueError(
                "Unknown or inactive similarity "
                "signal codes: "
                + ", ".join(
                    sorted(
                        the_unknown_codes
                    )
                )
            )

    the_saved_count = 0

    for the_candidate in candidates:
        the_insert = await db.execute(
            text(
                """
                INSERT INTO related_incident_candidate
                    (
                        related_incident_run_id,
                        report_id,
                        candidate_report_id,
                        relatedness_level,
                        similarity_score
                    )

                VALUES
                    (
                        :run_id,
                        :report_id,
                        :candidate_report_id,
                        :relatedness_level,
                        :similarity_score
                    )

                RETURNING
                    related_incident_candidate_id
                """
            ),
            {
                "run_id":
                    run_id,

                "report_id":
                    report_id,

                "candidate_report_id":
                    the_candidate
                    .candidate_report_id,

                "relatedness_level":
                    the_candidate
                    .relatedness_level
                    .value,

                "similarity_score":
                    the_candidate
                    .similarity_score,
            },
        )

        the_candidate_id = (
            the_insert.scalar_one()
        )

        for the_signal in (
            the_candidate.signals
        ):
            await db.execute(
                text(
                    """
                    INSERT INTO
                        related_incident_candidate_signal
                        (
                            related_incident_candidate_id,
                            similarity_signal_id,
                            signal_detail
                        )

                    VALUES
                        (
                            :candidate_id,
                            :signal_id,
                            :detail
                        )
                    """
                ),
                {
                    "candidate_id":
                        the_candidate_id,

                    "signal_id":
                        the_signal_ids[
                            the_signal.code
                        ],

                    "detail":
                        the_signal.detail,
                },
            )

        the_saved_count += 1

    return the_saved_count


async def finish_detection_run(
    db: AsyncSession,
    run_id: int,
    run_state: DetectionRunState,
) -> None:
    """
    Close a run with its final state. finished_at is required by the CHECK
    for every state except processing.
    """

    if (
        run_state
        == DetectionRunState.PROCESSING
    ):
        raise ValueError(
            "A run cannot be finished as processing"
        )

    await db.execute(
        text(
            """
            UPDATE related_incident_run

            SET
                run_state = :run_state,
                finished_at = now()

            WHERE
                related_incident_run_id = :run_id
            """
        ),
        {
            "run_id":
                run_id,

            "run_state":
                run_state.value,
        },
    )


# ===========================================================================
# WORKFLOW — reads
# ===========================================================================


async def get_report_identity(
    db: AsyncSession,
    report_reference: str,
) -> dict | None:
    """
    report_id, current owner and incident for one live report.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                r.report_id,
                r.report_reference,
                r.claimed_by_user_id,
                r.incident_id

            FROM report AS r

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL
            """
        ),
        {
            "report_reference":
                report_reference,
        },
    )

    the_row = (
        the_result
        .mappings()
        .first()
    )

    return (
        dict(the_row)
        if the_row is not None
        else None
    )


async def get_latest_detection_run(
    db: AsyncSession,
    report_id: int,
) -> dict | None:
    """
    The most recently started run for a report, whatever its rule version.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                related_incident_run_id,
                rule_version,
                run_state,
                started_at,
                finished_at

            FROM related_incident_run

            WHERE
                report_id =
                    :report_id

            ORDER BY
                started_at DESC,
                related_incident_run_id DESC

            LIMIT 1
            """
        ),
        {
            "report_id":
                report_id,
        },
    )

    the_row = (
        the_result
        .mappings()
        .first()
    )

    return (
        dict(the_row)
        if the_row is not None
        else None
    )


async def list_run_candidates(
    db: AsyncSession,
    run_id: int,
) -> list[dict]:
    """
    Candidates of one run with the candidate report's CURRENT owner and
    incident, which the service needs for the AC4 filter and decision state.

    Withdrawn candidates are excluded here.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                c.related_incident_candidate_id,
                c.candidate_report_id,

                r.report_reference
                    AS candidate_report_reference,

                r.claimed_by_user_id
                    AS candidate_claimed_by_user_id,

                r.incident_id
                    AS candidate_incident_id,

                c.relatedness_level,
                c.similarity_score

            FROM related_incident_candidate AS c

            JOIN report AS r
                ON r.report_id =
                   c.candidate_report_id

            WHERE
                c.related_incident_run_id =
                    :run_id

                AND r.deleted_at IS NULL

            ORDER BY
                CASE
                    c.relatedness_level

                    WHEN 'high'
                        THEN 1

                    WHEN 'medium'
                        THEN 2

                    ELSE 3
                END,

                c.similarity_score
                    DESC NULLS LAST,

                c.related_incident_candidate_id
            """
        ),
        {
            "run_id":
                run_id,
        },
    )

    return [
        dict(the_row)
        for the_row
        in the_result.mappings().all()
    ]


async def list_run_candidate_signals(
    db: AsyncSession,
    run_id: int,
) -> list[dict]:
    """
    Signals for every candidate of one run, with canonical labels.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                cs.related_incident_candidate_id,
                s.code,
                s.label,
                cs.signal_detail AS detail

            FROM related_incident_candidate_signal
                AS cs

            JOIN related_incident_candidate AS c
                ON c.related_incident_candidate_id =
                   cs.related_incident_candidate_id

            JOIN similarity_signal AS s
                ON s.similarity_signal_id =
                   cs.similarity_signal_id

            WHERE
                c.related_incident_run_id =
                    :run_id

            ORDER BY
                cs.related_incident_candidate_id,
                s.display_order,
                s.code
            """
        ),
        {
            "run_id":
                run_id,
        },
    )

    return [
        dict(the_row)
        for the_row
        in the_result.mappings().all()
    ]


async def list_latest_pair_decisions(
    db: AsyncSession,
    report_id: int,
    other_report_ids: list[int],
) -> list[dict]:
    """
    The latest human decision for each pair (report_id, other), found in
    either direction thanks to the stored pair_low / pair_high columns.
    """

    if not other_report_ids:
        return []

    the_result = await db.execute(
        text(
            """
            SELECT DISTINCT ON
                (
                    d.pair_low_report_id,
                    d.pair_high_report_id
                )

                CASE
                    WHEN d.report_id =
                         :report_id
                    THEN d.related_report_id
                    ELSE d.report_id
                END
                    AS other_report_id,

                d.decision,
                d.decided_at

            FROM report_relationship_decision AS d

            WHERE
                (
                    d.report_id =
                        :report_id

                    AND d.related_report_id
                        IN :other_ids
                )

                OR

                (
                    d.related_report_id =
                        :report_id

                    AND d.report_id
                        IN :other_ids
                )

            ORDER BY
                d.pair_low_report_id,
                d.pair_high_report_id,
                d.decided_at DESC
            """
        ).bindparams(
            bindparam(
                "other_ids",
                expanding=True,
            )
        ),
        {
            "report_id":
                report_id,

            "other_ids":
                other_report_ids,
        },
    )

    return [
        dict(the_row)
        for the_row
        in the_result.mappings().all()
    ]


async def get_latest_evidence_times(
    db: AsyncSession,
    report_ids: list[int],
) -> dict[
    int,
    datetime,
]:
    """
    Latest evidence upload per report. Used for the AC7 rule: a Not Related
    pair is suggested again only when new evidence arrived after the decision.
    """

    if not report_ids:
        return {}

    the_result = await db.execute(
        text(
            """
            SELECT
                report_id,
                max(uploaded_at)
                    AS latest_uploaded_at

            FROM evidence

            WHERE
                report_id IN :report_ids

            GROUP BY
                report_id
            """
        ).bindparams(
            bindparam(
                "report_ids",
                expanding=True,
            )
        ),
        {
            "report_ids":
                report_ids,
        },
    )

    return {
        the_row[
            "report_id"
        ]:
            the_row[
                "latest_uploaded_at"
            ]

        for the_row
        in the_result.mappings().all()
    }


async def get_comparison_side(
    db: AsyncSession,
    report_reference: str,
) -> dict | None:
    """
    Protected report detail for the side-by-side view. The service must
    confirm ownership BEFORE calling this.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                r.report_id,
                r.report_reference,
                r.claimed_by_user_id,

                cs.code AS status_code,
                cs.internal_label
                    AS status_label,

                tc.code
                    AS threat_category_code,

                tc.label
                    AS threat_category_label,

                r.observed_at,
                r.submitted_at,

                ds.name AS dive_site_name,
                ds.public_area_label,

                lc.code
                    AS location_confidence_code,

                r.estimated_depth_metres,
                r.description,

                i.incident_reference

            FROM report AS r

            JOIN case_status AS cs
                ON cs.case_status_id =
                   r.current_status_id

            JOIN threat_category AS tc
                ON tc.threat_category_id =
                   r.threat_category_id

            LEFT JOIN dive_session AS dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site AS ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            LEFT JOIN report_location AS rl
                ON rl.report_location_id =
                   r.report_location_id

            LEFT JOIN location_confidence AS lc
                ON lc.location_confidence_id =
                   rl.location_confidence_id

            LEFT JOIN incident AS i
                ON i.incident_id =
                   r.incident_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL
            """
        ),
        {
            "report_reference":
                report_reference,
        },
    )

    the_row = (
        the_result
        .mappings()
        .first()
    )

    if the_row is None:
        return None

    the_side = dict(
        the_row
    )

    # observation evidence only; E7 action evidence
    # (case_event_id set) is not part of a relatedness
    # comparison
    the_evidence = await db.execute(
        text(
            """
            SELECT
                evidence_id,
                media_type,
                captured_at

            FROM evidence

            WHERE
                report_id =
                    :report_id

                AND case_event_id
                    IS NULL

            ORDER BY
                display_order,
                evidence_id
            """
        ),
        {
            "report_id":
                the_side[
                    "report_id"
                ],
        },
    )

    the_side[
        "evidence"
    ] = [
        dict(the_evidence_row)
        for the_evidence_row
        in the_evidence.mappings().all()
    ]

    return the_side


async def find_candidate_in_latest_run(
    db: AsyncSession,
    report_id: int,
    candidate_report_id: int,
) -> dict | None:
    """
    The candidate row for this pair in the report's latest run, with that
    run's rule version (used as decision provenance) and its signals.
    """

    the_result = await db.execute(
        text(
            """
            WITH the_latest_run AS
            (
                SELECT
                    related_incident_run_id,
                    rule_version

                FROM related_incident_run

                WHERE
                    report_id =
                        :report_id

                ORDER BY
                    started_at DESC,
                    related_incident_run_id DESC

                LIMIT 1
            )

            SELECT
                c.related_incident_candidate_id,
                c.relatedness_level,
                lr.rule_version

            FROM related_incident_candidate
                AS c

            JOIN the_latest_run AS lr
                ON lr.related_incident_run_id =
                   c.related_incident_run_id

            WHERE
                c.candidate_report_id =
                    :candidate_report_id
            """
        ),
        {
            "report_id":
                report_id,

            "candidate_report_id":
                candidate_report_id,
        },
    )

    the_row = (
        the_result
        .mappings()
        .first()
    )

    if the_row is None:
        return None

    the_candidate = dict(
        the_row
    )

    the_signals = await db.execute(
        text(
            """
            SELECT
                s.code,
                s.label,
                cs.signal_detail AS detail

            FROM related_incident_candidate_signal
                AS cs

            JOIN similarity_signal AS s
                ON s.similarity_signal_id =
                   cs.similarity_signal_id

            WHERE
                cs.related_incident_candidate_id =
                    :candidate_id

            ORDER BY
                s.display_order,
                s.code
            """
        ),
        {
            "candidate_id":
                the_candidate[
                    "related_incident_candidate_id"
                ],
        },
    )

    the_candidate[
        "signals"
    ] = [
        dict(the_signal)
        for the_signal
        in the_signals.mappings().all()
    ]

    return the_candidate


async def get_latest_pair_decision_detail(
    db: AsyncSession,
    report_id: int,
    other_report_id: int,
) -> dict | None:
    """
    The latest decision on one pair, with labels for display.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                d.decision,

                rr.code
                    AS rejection_reason_code,

                rr.label
                    AS rejection_reason_label,

                i.incident_reference,

                u.display_name
                    AS decided_by_name,

                d.decided_at

            FROM report_relationship_decision
                AS d

            LEFT JOIN relationship_rejection_reason
                AS rr

                ON rr.relationship_rejection_reason_id =
                   d.relationship_rejection_reason_id

            LEFT JOIN incident AS i
                ON i.incident_id =
                   d.incident_id

            LEFT JOIN app_user AS u
                ON u.user_id =
                   d.decided_by

            WHERE
                d.pair_low_report_id =
                    least(
                        :report_id,
                        :other_report_id
                    )

                AND d.pair_high_report_id =
                    greatest(
                        :report_id,
                        :other_report_id
                    )

            ORDER BY
                d.decided_at DESC,
                d.report_relationship_decision_id
                    DESC

            LIMIT 1
            """
        ),
        {
            "report_id":
                report_id,

            "other_report_id":
                other_report_id,
        },
    )

    the_row = (
        the_result
        .mappings()
        .first()
    )

    return (
        dict(the_row)
        if the_row is not None
        else None
    )


async def list_rejection_reasons(
    db: AsyncSession,
) -> list[dict]:
    the_result = await db.execute(
        text(
            """
            SELECT
                code,
                label,
                requires_note

            FROM relationship_rejection_reason

            WHERE
                is_selectable

            ORDER BY
                display_order,
                code
            """
        )
    )

    return [
        dict(the_row)
        for the_row
        in the_result.mappings().all()
    ]


# ===========================================================================
# WORKFLOW — decisions (PostgreSQL functions only)
# ===========================================================================


async def confirm_same_incident(
    db: AsyncSession,
    report_reference: str,
    related_reference: str,
    coordinator_id: int,
    note: str | None,
    suggested_rule_version: str | None,
) -> dict:
    """
    Call reefcare_confirm_same_incident(). Ownership, incident reuse, the
    incident_id update and the decision row all happen inside PostgreSQL in
    one transaction. RC4xx errors propagate to the service for mapping.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                out_incident_id,
                out_incident_reference,
                out_report_relationship_decision_id,
                out_decided_at

            FROM reefcare_confirm_same_incident(
                :report_reference,
                :related_reference,
                :coordinator_id,
                :note,
                :suggested_rule_version
            )
            """
        ),
        {
            "report_reference":
                report_reference,

            "related_reference":
                related_reference,

            "coordinator_id":
                coordinator_id,

            "note":
                note,

            "suggested_rule_version":
                suggested_rule_version,
        },
    )

    return dict(
        the_result
        .mappings()
        .one()
    )


async def record_not_related(
    db: AsyncSession,
    report_reference: str,
    related_reference: str,
    coordinator_id: int,
    reason_code: str,
    note: str | None,
    suggested_rule_version: str | None,
) -> dict:
    """
    Call reefcare_record_not_related(). The reason code, its note rule and
    ownership are all checked inside PostgreSQL.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                out_report_relationship_decision_id,
                out_decided_at

            FROM reefcare_record_not_related(
                :report_reference,
                :related_reference,
                :coordinator_id,
                :reason_code,
                :note,
                :suggested_rule_version
            )
            """
        ),
        {
            "report_reference":
                report_reference,

            "related_reference":
                related_reference,

            "coordinator_id":
                coordinator_id,

            "reason_code":
                reason_code,

            "note":
                note,

            "suggested_rule_version":
                suggested_rule_version,
        },
    )

    return dict(
        the_result
        .mappings()
        .one()
    )