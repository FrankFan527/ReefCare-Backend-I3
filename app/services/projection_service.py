from app.schemas.case import (
    CaseOwnerResponse,
    CoordinatorCaseResponse,
    EvidenceSummary,
    PreciseLocationResponse,
)


def build_coordinator_case_projection(
    case,
    location,
    evidence_rows,
) -> CoordinatorCaseResponse:
    precise_location = None

    if location is not None:
        precise_location = (
            PreciseLocationResponse(
                latitude=location["latitude"],
                longitude=location["longitude"],
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
            evidence_id=row["evidence_id"],
            media_type=row["media_type"],
            captured_at=row["captured_at"],
            uploaded_at=row["uploaded_at"],
        )
        for row in evidence_rows
    ]

    return CoordinatorCaseResponse(
        report_reference=case[
            "report_reference"
        ],
        observer_id=case["observer_id"],
        threat=case["threat"],
        description=case["description"],
        estimated_depth_metres=case[
            "estimated_depth_metres"
        ],
        area=case["area"],
        precise_location=precise_location,
        status_code=case["status_code"],
        status_label=case["status_label"],
        submitted_at=case["submitted_at"],
        owner=CaseOwnerResponse(
            id=case["claimed_by_user_id"],
            display_name=case["claimed_by"],
        ),
        evidence=evidence,
    )