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


# ---------------------------------------------------------------------------
# Epic 9 Reef-Aware Dive Planning.
# ---------------------------------------------------------------------------


class PlanningBand(str, Enum):
    """
    Deterministic public planning-condition assessment.

    These values describe environmental conditions only.
    They are not safety, permission or operational
    clearance decisions.
    """

    MORE_FAVOURABLE = "more_favourable"
    MIXED = "mixed"
    LESS_FAVOURABLE = "less_favourable"

    # Provider or required forecast values are unavailable.
    UNAVAILABLE = "unavailable"

    # Requested date is outside the supported live
    # forecast window.
    OUT_OF_HORIZON = "out_of_horizon"

    # ReefCare does not have a usable planning position
    # for this site.
    NOT_ASSESSABLE = "not_assessable"


class SeasonalState(str, Enum):
    """
    Reviewed seasonal-reference vocabulary for US9.1.
    """

    MONSOON = "monsoon"
    TRANSITION = "transition"
    TYPICAL = "typical"

    # Explicitly means that no reviewed guidance currently
    # exists. Historical averages must not be substituted.
    UNREVIEWED = "unreviewed"