from app.schemas.case import (
    AIAssistedContext,
    CaseOwnerResponse,
    CaseTriageContext,
    CoordinatorCaseResponse,
    EvidenceSummary,
    InformationExchangeEntry,
    LatestDecisionResponse,
    PreciseLocationResponse,
)
from app.services.triage_priority_service import build_triage_cues


def build_coordinator_case_projection(
    case,
    location,
    evidence_rows,
    latest_decision=None,
    information_exchange=None,
    ai_assisted=None,
) -> CoordinatorCaseResponse:
    """
    Build the authorised coordinator case projection.

    observed_at is kept separate from submitted_at.

    latest_decision represents the most recent persisted
    US5.4 response decision. A case without a decision
    returns latestDecision = null.

    US5.2 groups what the coordinator sees into three kinds
    of claim, and keeps them structurally apart:

      the report fields   what the Observer said
      latest_decision     what the Coordinator concluded
      ai_assisted         what a model suggested

    AC2 asks that AI output is never presented as
    verification. Separating it in the response shape rather
    than by labelling it in prose means the frontend cannot
    accidentally render it as a finding, and a reader of the
    JSON can tell the three apart without knowing how any of
    it was produced.

    triage_context is AC3: the same completeness, priority
    and age the queue shows, recomputed from the same rules
    so a case cannot appear one way in the list and another
    when opened.
    """

    precise_location = None

    if location is not None:
        precise_location = (
            PreciseLocationResponse(
                latitude=location[
                    "latitude"
                ],
                longitude=location[
                    "longitude"
                ],
                uncertainty_metres=location[
                    "uncertainty_metres"
                ],
                confidence_label=location[
                    "confidence_label"
                ],
                source_label=location[
                    "source_label"
                ],
                relocation_notes=location[
                    "relocation_notes"
                ],
            )
        )

    evidence = [
        EvidenceSummary(
            evidence_id=row[
                "evidence_id"
            ],
            media_type=row[
                "media_type"
            ],
            captured_at=row[
                "captured_at"
            ],
            uploaded_at=row[
                "uploaded_at"
            ],
        )
        for row in evidence_rows
    ]

    latest_decision_response = None

    if latest_decision is not None:
        latest_decision_response = (
            LatestDecisionResponse(
                response_type=latest_decision[
                    "response_type"
                ],
                notes=latest_decision[
                    "decision_note"
                ],
                referred_to=latest_decision[
                    "referred_to"
                ],
                decided_at=latest_decision[
                    "decided_at"
                ],
            )
        )

    # US5.2 AC3. The same three arguments the queue passes,
    # so the two views cannot diverge.
    (
        the_evidence_completeness,
        the_priority,
        the_priority_reasons,
    ) = build_triage_cues(
        threat_code=case["threat_code"],
        evidence_count=case["evidence_count"],
        has_location_detail=bool(
            case["has_location_detail"]
        ),
        description_length=case[
            "description_length"
        ],
        hours_in_queue=case[
            "hours_in_queue"
        ],
    )

    triage_context = CaseTriageContext(
        evidence_completeness=(
            the_evidence_completeness
        ),
        evidence_count=case[
            "evidence_count"
        ],
        priority=the_priority,
        priority_reasons=(
            the_priority_reasons
        ),
        hours_in_queue=case[
            "hours_in_queue"
        ],
    )

    # US5.2 AC2. Null throughout Iteration 2 until US5.6
    # exists. is_unverified_ai_output is set here rather
    # than left to the caller so the flag cannot be omitted
    # by whoever wires the brief in later.
    ai_assisted_context = None

    if ai_assisted is not None:
        ai_assisted_context = AIAssistedContext(
            triage_brief=ai_assisted.get(
                "triage_brief"
            ),
            generated_at=ai_assisted.get(
                "generated_at"
            ),
            is_unverified_ai_output=True,
        )

    # US6.3 AC4. Requests and responses in one ordered list:
    # an answer means little without the question above it.
    exchange_entries = []

    if information_exchange is not None:
        exchange_entries = [
            InformationExchangeEntry(
                event_type=row[
                    "event_type"
                ],
                message=row["message"],
                occurred_at=row[
                    "occurred_at"
                ],
                actor_user_id=row[
                    "actor_user_id"
                ],
                actor_display_name=row[
                    "actor_display_name"
                ],
            )
            for row in information_exchange
        ]

    return CoordinatorCaseResponse(
        report_reference=case[
            "report_reference"
        ],
        observer_id=case[
            "observer_id"
        ],
        threat=case[
            "threat"
        ],
        description=case[
            "description"
        ],
        observed_at=case[
            "observed_at"
        ],
        estimated_depth_metres=case[
            "estimated_depth_metres"
        ],
        area=case[
            "area"
        ],
        precise_location=precise_location,
        status_code=case[
            "status_code"
        ],
        status_label=case[
            "status_label"
        ],
        submitted_at=case[
            "submitted_at"
        ],
        owner=CaseOwnerResponse(
            id=case[
                "claimed_by_user_id"
            ],
            display_name=case[
                "claimed_by"
            ],
        ),
        evidence=evidence,
        latest_decision=(
            latest_decision_response
        ),
        triage_context=triage_context,
        ai_assisted=ai_assisted_context,
        information_exchange=(
            exchange_entries
        ),
    )