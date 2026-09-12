from enum import Enum


class UserRole(str, Enum):
    """
    Authenticated ReefCare user roles.

    Values must match app_role.code in PostgreSQL.
    """

    OBSERVER = "observer"
    CASE_COORDINATOR = "case_coordinator"
    SYSTEM_ADMIN = "system_administrator"

    CONSERVATION_RESPONDER = (
        "conservation_responder"
    )
    DIVE_OPERATOR = "dive_operator"


class LocationSource(str, Enum):
    """
    Canonical observation-location provenance codes.

    Values must exactly match location_source.code in
    PostgreSQL.

    Do not create alternate frontend/backend names for
    these values.
    """

    NAMED_DIVE_SITE = "named_dive_site"
    MANUAL_MAP_PIN = "manual_map_pin"
    ENTERED_COORDINATES = "entered_coordinates"
    DEVICE_METADATA = "device_metadata"
    UNKNOWN = "unknown"


class CaseStatus(str, Enum):
    """
    Case status codes.

    Values must match case_status.code in PostgreSQL.
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    RECEIVED = "received"
    CLAIMED = "claimed"
    UNDER_REVIEW = "under_review"
    NEEDS_MORE_INFO = "needs_more_info"
    EVIDENCE_ACCEPTED = "evidence_accepted"

    MONITORING = "monitoring"
    REFERRED = "referred"
    RESPONSE_RECOMMENDED = (
        "response_recommended"
    )


    RESPONSE_PLANNED = "response_planned"
    RESPONSE_COMPLETE = (
        "response_complete"
    )

    CLOSED_NO_ACTION = "closed_no_action"
    CLOSED_NOT_SUBSTANTIATED = (
        "closed_not_substantiated"
    )
    CLOSED_NO_PARTNER = "closed_no_partner"
    CLOSED_LOGGED = "closed_logged"


    CLOSED_RESOLVED = "closed_resolved"

class ActionState(str, Enum):
    """
    US7.1 conservation action states.

    Values must match the case_action_state_valid CHECK in
    PostgreSQL.

    Two distinct stored values rather than a nullable
    completion flag. US7.1 AC4 requires that a planned
    action is never rendered as a completed one, and a
    boolean defaulting to false is easier to misread at the
    display layer than a value that names itself.
    """

    ACTION_PLANNED = "action_planned"
    ACTION_TAKEN = "action_taken"


class CaseDecision(str, Enum):
    """
    API/business-level decision vocabulary.
    """

    EVIDENCE_ACCEPTED = "EVIDENCE_ACCEPTED"

    MORE_INFORMATION_REQUIRED = (
        "MORE_INFORMATION_REQUIRED"
    )

    REFER = "REFER"

    NO_FURTHER_ACTION = (
        "NO_FURTHER_ACTION"
    )

    NO_RESPONSIBLE_PARTNER = (
        "NO_RESPONSIBLE_PARTNER"
    )


class ClosureReason(str, Enum):
    """
    Values match closure_reason.code in PostgreSQL.
    """

    REFERRED_TO_ANOTHER_ORGANISATION = (
        "referred_other_org"
    )

    MONITORED_NO_ACTION_REQUIRED = (
        "monitored_no_action"
    )

    NOT_SUBSTANTIATED = (
        "not_substantiated"
    )

    NO_RESPONSIBLE_PARTNER_AVAILABLE = (
        "no_responsible_partner"
    )

    LOGGED_FOR_REFERENCE = (
        "logged_for_reference"
    )

    RESOLVED_OR_ACTED_ON = (
        "resolved_acted_on"
    )

    MERGED_WITH_RELATED_INCIDENT = (
        "merged_related"
    )