# ---------------------------------------------------------------------------
# Triage cues for the coordinator queue (US5.1 AC1, US5.7).
#
# Pure functions. Nothing here touches the database, which means the rules can
# be read, argued about and changed without anyone opening a repository, and
# they can be unit tested without a connection.
#
# US5.7 AC3 draws the line this module must not cross: a priority cue may order
# attention, but it must never verify the threat, close the case or make the
# conservation decision. Nothing below writes anything.
#
# US5.7 AC1 names five conditions: active harm, trapped wildlife, live coral
# being actively affected, sufficient reviewable evidence, extended queue age.
# Two of those are measurable from stored data. The other three are not:
# nothing in the schema records whether harm is ongoing or whether an animal is
# trapped. The observer is prompted to mention it, but it lands in free-text
# description, and reading that would be the opaque inference the acceptance
# criterion exists to avoid.
#
# So threat_category stands in for them. It is a value the observer chose from
# a controlled list, so treating "ghost gear" as implying entanglement risk is
# reading a declaration rather than guessing at prose. Each substitution names
# itself in the reason string, so a coordinator can see the inference and
# disagree with it.
#
# This narrows what AC1 describes. It is recorded here rather than buried, and
# needs product sign-off before release.
#
# ASCII only, deliberately. The reason strings are returned through the API and
# rendered by the frontend, and a stray non-ASCII character survives a round
# trip only if every layer agrees on the encoding. Plain hyphens always do.
# ---------------------------------------------------------------------------

from app.schemas.case import CasePriority, EvidenceCompleteness


# A description shorter than this is treated as not yet reviewable. "Saw a net"
# is a report; it is not something a coordinator can assess without asking.
MINIMUM_USEFUL_DESCRIPTION_LENGTH: int = 30


# Queue age thresholds, in hours. Three days is roughly a working week's
# patience; seven days means the report has waited through a full cycle of dive
# trips and nobody has looked at it.
QUEUE_AGE_ELEVATED_HOURS: int = 72
QUEUE_AGE_HIGH_HOURS: int = 168


# threat_category codes that stand in for the three unmeasurable AC1
# conditions. The value is the reason shown to the coordinator, so the
# substitution is visible rather than implied.
#
# marine_debris and unsure are absent on purpose. Debris is usually static, and
# an unsure report is by definition one the observer could not characterise, so
# inferring urgency from it would be inventing information.
THREAT_URGENCY_REASON: dict[str, str] = {
    "ghost_gear": "Ghost gear - risk of continued entanglement",
    "coral_bleaching": "Bleaching - live coral may be actively affected",
    "physical_damage": "Physical damage - harm may be ongoing",
}


# Points at which the accumulated cues change the displayed band.
HIGH_PRIORITY_SCORE: int = 3
MEDIUM_PRIORITY_SCORE: int = 1


def assess_evidence_completeness(
    evidence_count: int,
    has_location_detail: bool,
    description_length: int,
) -> EvidenceCompleteness:
    """
    Describe how much of a report a coordinator can actually review.

    A photograph is the deciding signal, because it is what US5.3's first
    question asks about: whether the evidence is usable at all. A report with
    no photograph cannot pass that question however carefully it is written, so
    it is MINIMAL regardless of what else is present.

    Above that, COMPLETE means the coordinator has everything needed to assess
    without going back to the observer: something to look at, somewhere to find
    it, and a description with enough in it to read.
    """

    if evidence_count < 1:
        return EvidenceCompleteness.MINIMAL

    the_description_is_substantive = (
        description_length >= MINIMUM_USEFUL_DESCRIPTION_LENGTH
    )

    if has_location_detail and the_description_is_substantive:
        return EvidenceCompleteness.COMPLETE

    return EvidenceCompleteness.PARTIAL


def assess_priority(
    threat_code: str,
    evidence_completeness: EvidenceCompleteness,
    hours_in_queue: int,
) -> tuple[CasePriority, list[str]]:
    """
    Return a priority band and the reasons that produced it.

    The reasons are the point. US5.7 AC2 asks for a priority the coordinator
    can understand, and a bare label like "high" is not understandable: it only
    reports what the system concluded, not why. Returning the rules that fired
    lets a coordinator judge whether the reasoning applies to the case in front
    of them.

    Queue age is deliberately the heaviest single cue. A report nobody has
    looked at for a week is a failure of the process regardless of what it
    contains, and it is the one condition the system can measure without
    interpreting anything.
    """

    the_score: int = 0
    the_reasons: list[str] = []

    # Condition: the declared threat stands in for active harm, trapped
    # wildlife or live coral being affected.
    the_threat_reason = THREAT_URGENCY_REASON.get(threat_code)

    if the_threat_reason is not None:
        the_score += 1
        the_reasons.append(the_threat_reason)

    # Condition: sufficient reviewable evidence.
    if evidence_completeness == EvidenceCompleteness.COMPLETE:
        the_score += 1
        the_reasons.append("Evidence is complete and ready to review")

    elif evidence_completeness == EvidenceCompleteness.MINIMAL:
        # Not a penalty, an explanation. A coordinator seeing a standard
        # priority should know it reflects what is missing rather than a
        # judgement that the report does not matter.
        the_reasons.append("No photograph submitted yet")

    # Condition: extended queue age. The two thresholds do not stack; the
    # higher one replaces the lower.
    if hours_in_queue >= QUEUE_AGE_HIGH_HOURS:
        the_score += 2
        the_reasons.append(
            f"Waiting {hours_in_queue} hours - over seven days"
        )

    elif hours_in_queue >= QUEUE_AGE_ELEVATED_HOURS:
        the_score += 1
        the_reasons.append(
            f"Waiting {hours_in_queue} hours - over three days"
        )

    if the_score >= HIGH_PRIORITY_SCORE:
        the_priority = CasePriority.HIGH

    elif the_score >= MEDIUM_PRIORITY_SCORE:
        the_priority = CasePriority.MEDIUM

    else:
        the_priority = CasePriority.STANDARD

    if not the_reasons:
        the_reasons.append("No priority conditions met")

    return the_priority, the_reasons


def build_triage_cues(
    threat_code: str,
    evidence_count: int,
    has_location_detail: bool,
    description_length: int,
    hours_in_queue: int,
) -> tuple[EvidenceCompleteness, CasePriority, list[str]]:
    """
    Produce both cues for one queue row.

    Completeness is assessed first, because priority depends on it.
    """

    the_completeness = assess_evidence_completeness(
        evidence_count=evidence_count,
        has_location_detail=has_location_detail,
        description_length=description_length,
    )

    the_priority, the_reasons = assess_priority(
        threat_code=threat_code,
        evidence_completeness=the_completeness,
        hours_in_queue=hours_in_queue,
    )

    return the_completeness, the_priority, the_reasons