# ---------------------------------------------------------------------------
# US7.1 Conservation follow-up and US7.2 follow-up monitoring — contracts.
#
# These sit alongside the Iteration 2 action contracts in app/schemas/action.py
# rather than replacing them. The I2 /actions routes keep working unchanged;
# E7 adds the wider follow-up record on the same case_action table.
#
# Three kinds of follow-up, deliberately distinct (US7.1 AC5):
#
#   action          an intervention planned or taken by ReefCare or a partner
#   monitoring      a dated observation visit with a human-reviewed condition
#   sourced_outcome an outcome reported by an outside organisation after a
#                   referral. It never becomes an accepted or completed action
# ---------------------------------------------------------------------------

from datetime import date, datetime
from enum import Enum

from pydantic import Field, model_validator

from app.core.enums import CaseStatus
from app.schemas.common import APIModel


# ---------------------------------------------------------------------------
# Vocabularies. Values match the CHECK constraints and reference rows in
# i3_e7_follow_up.sql.
# ---------------------------------------------------------------------------

class FollowUpType(str, Enum):
    ACTION = "action"
    MONITORING = "monitoring"
    SOURCED_OUTCOME = "sourced_outcome"


class FollowUpState(str, Enum):
    ACTION_PLANNED = "action_planned"
    ACTION_TAKEN = "action_taken"
    MONITORING_RECORDED = "monitoring_recorded"
    OUTCOME_RECORDED = "outcome_recorded"


class RecordingLevel(str, Enum):
    """
    Who the record speaks for (Proposal 8.9). This is what keeps a
    Coordinator's own summary from being displayed as an organisation's record.
    """

    COORDINATOR_SUMMARY = "coordinator_summary"
    RESPONDER_RECORD = "responder_record"
    EXTERNALLY_SOURCED = "externally_sourced"


# the state each follow-up type may carry, mirroring
# case_action_state_matches_type in the migration
THE_STATES_FOR_TYPE: dict[FollowUpType, set[FollowUpState]] = {
    FollowUpType.ACTION: {
        FollowUpState.ACTION_PLANNED,
        FollowUpState.ACTION_TAKEN,
    },
    FollowUpType.MONITORING: {FollowUpState.MONITORING_RECORDED},
    FollowUpType.SOURCED_OUTCOME: {FollowUpState.OUTCOME_RECORDED},
}


# ---------------------------------------------------------------------------
# Reference options
# ---------------------------------------------------------------------------

class MonitoringConditionOption(APIModel):
    code: str
    label: str

    description: str | None = None


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class FollowUpCreate(APIModel):
    """
    US7.1 AC3 minimum set: type, state, date, responsible team or source,
    notes and recorded outcome, with optional evidence attached afterwards
    through the existing action-evidence route.

    Monitoring fields are rejected here: a monitoring record goes through
    POST /monitoring, which has its own required fields.
    """

    follow_up_type: FollowUpType
    follow_up_state: FollowUpState

    action_type_code: str = Field(min_length=1, max_length=100)

    recording_level: RecordingLevel = RecordingLevel.COORDINATOR_SUMMARY

    action_date: date | None = None

    responsible_team: str | None = Field(default=None, max_length=200)

    # where a sourced outcome came from: the organisation, and how it reached
    # ReefCare (US7.1 AC5)
    source_reference: str | None = Field(default=None, max_length=500)

    recorded_outcome: str | None = Field(default=None, max_length=2000)

    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def the_fields_match_the_type(self):
        if self.follow_up_state not in THE_STATES_FOR_TYPE[self.follow_up_type]:
            raise ValueError(
                f"followUpState {self.follow_up_state.value} is not valid for "
                f"followUpType {self.follow_up_type.value}"
            )

        if self.follow_up_type == FollowUpType.MONITORING:
            raise ValueError(
                "Record a monitoring visit through POST /monitoring, "
                "which captures the condition and next follow-up state"
            )

        if self.follow_up_type == FollowUpType.SOURCED_OUTCOME:
            if not (self.source_reference or "").strip():
                raise ValueError(
                    "sourceReference is required for a sourced outcome"
                )

            if not (self.recorded_outcome or "").strip():
                raise ValueError(
                    "recordedOutcome is required for a sourced outcome"
                )

            if self.action_date is None:
                raise ValueError(
                    "actionDate is required for a sourced outcome"
                )

        if (
            self.follow_up_state == FollowUpState.ACTION_TAKEN
            and self.action_date is None
        ):
            raise ValueError(
                "actionDate is required when followUpState is action_taken"
            )

        return self


class MonitoringCreate(APIModel):
    """
    US7.2. A dated observation visit.

    nextFollowUpRequired false means "no follow-up currently scheduled",
    which is a real answer rather than a missing one (AC2). A date may only
    accompany a required follow-up.
    """

    action_date: date

    condition_code: str = Field(min_length=1, max_length=50)

    observations: str = Field(min_length=1, max_length=2000)

    notes: str | None = Field(default=None, max_length=2000)

    responsible_team: str | None = Field(default=None, max_length=200)

    recording_level: RecordingLevel = RecordingLevel.COORDINATOR_SUMMARY

    next_follow_up_required: bool = False
    next_follow_up_date: date | None = None

    @model_validator(mode="after")
    def the_next_visit_is_consistent(self):
        if not self.next_follow_up_required and self.next_follow_up_date is not None:
            raise ValueError(
                "nextFollowUpDate may only be given when "
                "nextFollowUpRequired is true"
            )

        if (
            self.next_follow_up_required
            and self.next_follow_up_date is not None
            and self.next_follow_up_date < self.action_date
        ):
            raise ValueError(
                "nextFollowUpDate cannot be earlier than the visit date"
            )

        return self


class FollowUpCorrection(APIModel):
    """
    US7.1 AC8. A correction is appended as a new record that supersedes the
    original, because follow-up records are append-only. Only the fields a
    Coordinator may restate are accepted; the type and the case cannot change.
    """

    follow_up_state: FollowUpState | None = None

    action_date: date | None = None

    responsible_team: str | None = Field(default=None, max_length=200)

    recorded_outcome: str | None = Field(default=None, max_length=2000)

    notes: str | None = Field(default=None, max_length=2000)

    correction_reason: str = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class FollowUpEvidenceSummary(APIModel):
    """
    Safe metadata only. The image streams through the existing authenticated
    evidence route; the private storage key is never returned.
    """

    evidence_id: int
    media_type: str

    file_size_bytes: int | None = None
    uploaded_at: datetime


class FollowUpResponse(APIModel):
    case_action_id: int
    case_event_id: int

    report_reference: str

    follow_up_type: FollowUpType
    follow_up_state: FollowUpState
    recording_level: RecordingLevel

    action_type_code: str
    action_type_label: str

    action_date: date | None = None

    responsible_team: str | None = None
    source_reference: str | None = None

    observations: str | None = None
    recorded_outcome: str | None = None
    notes: str | None = None

    # monitoring only
    condition_code: str | None = None
    condition_label: str | None = None
    condition_reviewed_by_name: str | None = None

    next_follow_up_required: bool = False
    next_follow_up_date: date | None = None

    # US7.1 AC8: the record this one replaced, and whether it was itself
    # replaced by a later correction
    supersedes_case_action_id: int | None = None
    superseded_by_case_action_id: int | None = None

    status_code: CaseStatus

    created_by: int
    created_by_name: str | None = None
    created_at: datetime

    evidence: list[FollowUpEvidenceSummary] = Field(default_factory=list)


class FollowUpListResponse(APIModel):
    report_reference: str

    items: list[FollowUpResponse] = Field(default_factory=list)
    total: int

    # US7.1 AC7: an honest empty state rather than an inferred one
    message: str | None = None
