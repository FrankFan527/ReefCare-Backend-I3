from enum import Enum


class UserRole(str, Enum):
    """
    Authenticated Iteration 1 user roles.

    Values must match app_role.code in PostgreSQL.
    Public Visitor is not stored as a database role because
    public visitors do not have authenticated accounts.
    """

    OBSERVER = "observer"
    CASE_COORDINATOR = "case_coordinator"
    SYSTEM_ADMIN = "system_administrator"


class CaseStatus(str, Enum):
    """
    Iteration 1 case status codes.

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

    CLOSED_NO_ACTION = "closed_no_action"
    CLOSED_NOT_SUBSTANTIATED = "closed_not_substantiated"
    CLOSED_NO_PARTNER = "closed_no_partner"
    CLOSED_LOGGED = "closed_logged"


class CaseDecision(str, Enum):
    """
    API/business-level decision vocabulary.

    Important:
    These values do NOT map directly to one database column.
    PostgreSQL stores decision details across fields such as
    evidence_usable, observation_credible and response_type.
    """

    EVIDENCE_ACCEPTED = "EVIDENCE_ACCEPTED"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    REFER = "REFER"
    NO_FURTHER_ACTION = "NO_FURTHER_ACTION"
    NO_RESPONSIBLE_PARTNER = "NO_RESPONSIBLE_PARTNER"


class ClosureReason(str, Enum):
    """
    Values match closure_reason.code in PostgreSQL.
    """

    REFERRED_TO_ANOTHER_ORGANISATION = "referred_other_org"
    MONITORED_NO_ACTION_REQUIRED = "monitored_no_action"
    NOT_SUBSTANTIATED = "not_substantiated"
    NO_RESPONSIBLE_PARTNER_AVAILABLE = "no_responsible_partner"
    LOGGED_FOR_REFERENCE = "logged_for_reference"

    # Seeded for later iterations, not selectable in Iteration 1.
    RESOLVED_OR_ACTED_ON = "resolved_acted_on"
    MERGED_WITH_RELATED_INCIDENT = "merged_related"