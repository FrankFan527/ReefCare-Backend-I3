from app.schemas.case import (
    CaseOwnerResponse,
    CoordinatorCaseResponse,
    EvidenceSummary,
    LatestDecisionResponse,
    PreciseLocationResponse,
)


def build_coordinator_case_projection(
    case,
    location,
    evidence_rows,
    latest_decision=None,
) -> CoordinatorCaseResponse:
    """
    Build the authorised coordinator case projection.

    observed_at is kept separate from submitted_at.

    latest_decision represents the most recent persisted
    US5.4 response decision. A case without a decision
    returns latestDecision = null.
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
    )