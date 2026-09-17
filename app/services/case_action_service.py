# ---------------------------------------------------------------------------
# Conservation action policy (US7.1 / API-11 / API-17).
# ---------------------------------------------------------------------------

from datetime import date

from fastapi import UploadFile
from sqlalchemy.exc import (
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.enums import (
    ActionState,
    CaseStatus,
)
from app.core.exceptions import (
    DatabaseOperationError,
    DomainValidationError,
    NotFoundError,
    WorkflowError,
)
from app.repositories.case_action_repository import (
    get_action_type,
    get_case_action_for_report,
    get_latest_action_event_id,
    insert_standalone_action_event,
    list_action_evidence_metadata,
    list_case_actions,
    list_selectable_action_types,
    save_action_evidence,
    save_case_action,
)
from app.repositories.case_repository import (
    change_status,
)
from app.services.case_workflow_service import (
    load_owned_case,
    validate_status_transition,
)
from app.services.evidence_service import (
    delete_private_evidence,
    store_private_evidence,
    validate_photo,
)


ACTION_EVENT_TYPE = (
    "action_recorded"
)


STATUS_FOR_ACTION_STATE: dict[
    str,
    str,
] = {
    ActionState.ACTION_PLANNED.value:
        CaseStatus.RESPONSE_PLANNED.value,

    ActionState.ACTION_TAKEN.value:
        CaseStatus.RESPONSE_COMPLETE.value,
}


PERMITTED_STATUSES_FOR_ACTION_STATE: dict[
    str,
    set[str],
] = {
    ActionState.ACTION_PLANNED.value: {
        CaseStatus.RESPONSE_RECOMMENDED.value,
        CaseStatus.RESPONSE_PLANNED.value,
    },

    ActionState.ACTION_TAKEN.value: {
        CaseStatus.RESPONSE_PLANNED.value,
        CaseStatus.RESPONSE_COMPLETE.value,
    },
}


def validate_action_state_against_case(
    action_state: str,
    current_status_code: str,
) -> None:
    permitted = (
        PERMITTED_STATUSES_FOR_ACTION_STATE
        .get(
            action_state
        )
    )

    if permitted is None:
        raise DomainValidationError(
            "Unknown action state: "
            f"{action_state}"
        )

    if (
        current_status_code
        not in permitted
    ):
        raise WorkflowError(
            "An action cannot be recorded "
            "while the case is "
            f"{current_status_code}. "
            "Record an Intervention Required "
            "decision first."
        )


async def load_selectable_action_type(
    db: AsyncSession,
    action_type_code: str,
) -> dict:
    action_type = await get_action_type(
        db=db,
        action_type_code=(
            action_type_code
        ),
    )

    if action_type is None:
        raise DomainValidationError(
            "Unknown action type: "
            f"{action_type_code}"
        )

    if not action_type[
        "is_selectable"
    ]:
        raise WorkflowError(
            "Action type "
            f"{action_type_code} "
            "is not currently selectable"
        )

    return action_type


async def record_action(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    action_type_code: str,
    action_state: str,
    action_date: (
        date | None
    ),
    responsible_team: (
        str | None
    ),
    notes: (
        str | None
    ),
) -> dict:
    case = await load_owned_case(
        db=db,
        report_reference=(
            report_reference
        ),
        coordinator_id=(
            coordinator_id
        ),
    )

    validate_action_state_against_case(
        action_state=(
            action_state
        ),
        current_status_code=(
            case[
                "status_code"
            ]
        ),
    )

    action_type = (
        await load_selectable_action_type(
            db=db,
            action_type_code=(
                action_type_code
            ),
        )
    )

    target_status = (
        STATUS_FOR_ACTION_STATE[
            action_state
        ]
    )

    case_moves = (
        case[
            "status_code"
        ]
        != target_status
    )

    if case_moves:
        await validate_status_transition(
            db=db,
            from_status_code=(
                case[
                    "status_code"
                ]
            ),
            to_status_code=(
                target_status
            ),
        )

        resulting_status = (
            await change_status(
                db=db,
                report_reference=(
                    report_reference
                ),
                status_code=(
                    target_status
                ),
                actor_user_id=(
                    coordinator_id
                ),
                note=notes,
                event_type=(
                    ACTION_EVENT_TYPE
                ),
            )
        )

        case_event_id = (
            await get_latest_action_event_id(
                db=db,
                report_reference=(
                    report_reference
                ),
                coordinator_id=(
                    coordinator_id
                ),
            )
        )

    else:
        resulting_status = (
            case[
                "status_code"
            ]
        )

        case_event_id = (
            await insert_standalone_action_event(
                db=db,
                report_reference=(
                    report_reference
                ),
                coordinator_id=(
                    coordinator_id
                ),
                note=notes,
            )
        )

    if case_event_id is None:
        raise DatabaseOperationError(
            "The action history event "
            "could not be resolved"
        )

    saved = await save_case_action(
        db=db,
        report_reference=(
            report_reference
        ),
        case_event_id=(
            case_event_id
        ),
        action_type_id=(
            action_type[
                "action_type_id"
            ]
        ),
        action_state=(
            action_state
        ),
        action_date=(
            action_date
        ),
        responsible_team=(
            responsible_team
        ),
        notes=notes,
        created_by=(
            coordinator_id
        ),
    )

    if not saved:
        raise DatabaseOperationError(
            "The action could not be recorded"
        )

    return {
        "case_action_id":
            saved[
                "case_action_id"
            ],

        "case_event_id":
            saved[
                "case_event_id"
            ],

        "report_reference":
            report_reference,

        "action_type_code":
            action_type[
                "code"
            ],

        "action_type_label":
            action_type[
                "label"
            ],

        "action_state":
            saved[
                "action_state"
            ],

        "action_date":
            saved[
                "action_date"
            ],

        "responsible_team":
            saved[
                "responsible_team"
            ],

        "notes":
            saved[
                "notes"
            ],

        "status_code":
            resulting_status,

        "created_by":
            saved[
                "created_by"
            ],

        "created_by_name":
            saved[
                "created_by_name"
            ],

        "created_at":
            saved[
                "created_at"
            ],

        "evidence":
            [],
    }


async def list_actions_for_owned_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
) -> list[dict]:
    await load_owned_case(
        db=db,
        report_reference=(
            report_reference
        ),
        coordinator_id=(
            coordinator_id
        ),
    )

    actions = await list_case_actions(
        db=db,
        report_reference=(
            report_reference
        ),
    )

    evidence_rows = (
        await list_action_evidence_metadata(
            db=db,
            report_reference=(
                report_reference
            ),
        )
    )

    by_action: dict[
        int,
        list[dict],
    ] = {}

    for row in evidence_rows:
        by_action.setdefault(
            row[
                "case_action_id"
            ],
            [],
        ).append(
            {
                "evidence_id":
                    row[
                        "evidence_id"
                    ],

                "media_type":
                    row[
                        "media_type"
                    ],

                "file_size_bytes":
                    row[
                        "file_size_bytes"
                    ],

                "uploaded_at":
                    row[
                        "uploaded_at"
                    ],
            }
        )

    result = []

    for action in actions:
        item = dict(
            action
        )

        item[
            "evidence"
        ] = by_action.get(
            item[
                "case_action_id"
            ],
            [],
        )

        result.append(
            item
        )

    return result


async def attach_evidence_to_action(
    db: AsyncSession,
    report_reference: str,
    action_id: int,
    coordinator_id: int,
    photo: UploadFile,
) -> dict:
    await load_owned_case(
        db=db,
        report_reference=(
            report_reference
        ),
        coordinator_id=(
            coordinator_id
        ),
    )

    action = (
        await get_case_action_for_report(
            db=db,
            report_reference=(
                report_reference
            ),
            action_id=(
                action_id
            ),
        )
    )

    if action is None:
        raise NotFoundError(
            "Action not found"
        )

    content = (
        await validate_photo(
            photo
        )
    )

    stored_file = (
        await store_private_evidence(
            photo=photo,
            content=content,
        )
    )

    try:
        evidence = (
            await save_action_evidence(
                db=db,
                report_reference=(
                    report_reference
                ),
                case_event_id=(
                    action[
                        "case_event_id"
                    ]
                ),
                uploaded_by_user_id=(
                    coordinator_id
                ),
                file_reference=(
                    stored_file
                    .file_reference
                ),
                file_size_bytes=(
                    stored_file
                    .file_size_bytes
                ),
            )
        )

        if evidence is None:
            await db.rollback()

            await delete_private_evidence(
                stored_file
                .file_reference
            )

            raise NotFoundError(
                "Report not found"
            )

        await db.commit()

    except SQLAlchemyError as exc:
        await db.rollback()

        await delete_private_evidence(
            stored_file
            .file_reference
        )

        raise DatabaseOperationError(
            "The action evidence "
            "could not be recorded"
        ) from exc

    return {
        "evidence_id":
            evidence[
                "evidence_id"
            ],

        "case_action_id":
            action_id,

        "media_type":
            evidence[
                "media_type"
            ],

        "file_size_bytes":
            evidence[
                "file_size_bytes"
            ],

        "uploaded_at":
            evidence[
                "uploaded_at"
            ],
    }


async def list_action_type_options(
    db: AsyncSession,
) -> list[dict]:
    return await list_selectable_action_types(
        db=db
    )