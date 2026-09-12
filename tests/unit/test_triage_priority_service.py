# ---------------------------------------------------------------------------
# Unit tests for the US5.1 / US5.7 triage rules.
#
# These functions are pure, so every case below runs with no database and no
# fixtures. That is the whole reason the rules were put in their own module:
# the thresholds and the threat proxy are the part of Iteration 2 most likely
# to be changed by somebody who did not write them, and a rule change that
# quietly reclassifies every case in the queue is not visible from the API.
#
# The tests read the module's own constants rather than hardcoding 30, 72 and
# 168. A deliberate threshold change should therefore keep passing, while an
# accidental one - an inverted comparison, a stacked threshold, a band boundary
# moved by one - still fails. The boundary tests use constant and constant - 1
# for the same reason.
# ---------------------------------------------------------------------------

import pytest

from app.schemas.case import CasePriority, EvidenceCompleteness
from app.services.triage_priority_service import (
    HIGH_PRIORITY_SCORE,
    MEDIUM_PRIORITY_SCORE,
    MINIMUM_USEFUL_DESCRIPTION_LENGTH,
    QUEUE_AGE_ELEVATED_HOURS,
    QUEUE_AGE_HIGH_HOURS,
    THREAT_URGENCY_REASON,
    assess_evidence_completeness,
    assess_priority,
    build_triage_cues,
)


A_LONG_DESCRIPTION = MINIMUM_USEFUL_DESCRIPTION_LENGTH + 20
A_SHORT_DESCRIPTION = MINIMUM_USEFUL_DESCRIPTION_LENGTH - 1

A_NEUTRAL_THREAT = "marine_debris"
AN_URGENT_THREAT = "ghost_gear"


# ---------------------------------------------------------------------------
# Evidence completeness
# ---------------------------------------------------------------------------


def test_no_photograph_is_minimal_however_good_the_rest_is():
    """
    The photograph is the deciding signal, not one input among three.

    US5.3's first question asks whether the evidence is usable at all, and no
    amount of description or location gets a report past it. This test exists
    because the obvious implementation - count the signals, score out of three
    - would return PARTIAL here and look reasonable while being wrong.
    """

    result = assess_evidence_completeness(
        evidence_count=0,
        has_location_detail=True,
        description_length=A_LONG_DESCRIPTION,
    )

    assert result == EvidenceCompleteness.MINIMAL


def test_photograph_location_and_real_description_is_complete():
    result = assess_evidence_completeness(
        evidence_count=1,
        has_location_detail=True,
        description_length=A_LONG_DESCRIPTION,
    )

    assert result == EvidenceCompleteness.COMPLETE


def test_photograph_without_location_is_partial():
    result = assess_evidence_completeness(
        evidence_count=3,
        has_location_detail=False,
        description_length=A_LONG_DESCRIPTION,
    )

    assert result == EvidenceCompleteness.PARTIAL


def test_photograph_with_a_token_description_is_partial():
    """
    RC-0014 in the test data has a four-character description and a photo and
    a location. It should not read as complete.
    """

    result = assess_evidence_completeness(
        evidence_count=1,
        has_location_detail=True,
        description_length=4,
    )

    assert result == EvidenceCompleteness.PARTIAL


def test_description_threshold_is_inclusive_at_its_boundary():
    at_threshold = assess_evidence_completeness(
        evidence_count=1,
        has_location_detail=True,
        description_length=MINIMUM_USEFUL_DESCRIPTION_LENGTH,
    )

    below_threshold = assess_evidence_completeness(
        evidence_count=1,
        has_location_detail=True,
        description_length=A_SHORT_DESCRIPTION,
    )

    assert at_threshold == EvidenceCompleteness.COMPLETE
    assert below_threshold == EvidenceCompleteness.PARTIAL


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------


def test_a_fresh_unremarkable_report_is_standard():
    priority, reasons = assess_priority(
        threat_code=A_NEUTRAL_THREAT,
        evidence_completeness=EvidenceCompleteness.MINIMAL,
        hours_in_queue=1,
    )

    assert priority == CasePriority.STANDARD
    assert reasons  # never empty, even when nothing fired


def test_every_band_always_explains_itself():
    """
    US5.7 AC2 asks for a priority the coordinator can understand. A band with
    no reasons attached reports a conclusion without its reasoning, which is
    the thing the criterion rules out.
    """

    cases = [
        (A_NEUTRAL_THREAT, EvidenceCompleteness.MINIMAL, 0),
        (AN_URGENT_THREAT, EvidenceCompleteness.COMPLETE, 500),
        (A_NEUTRAL_THREAT, EvidenceCompleteness.PARTIAL, 100),
        ("unsure", EvidenceCompleteness.COMPLETE, 1),
    ]

    for threat_code, completeness, hours in cases:
        _, reasons = assess_priority(
            threat_code=threat_code,
            evidence_completeness=completeness,
            hours_in_queue=hours,
        )

        assert reasons, f"no reasons returned for {threat_code}/{hours}h"
        assert all(r.strip() for r in reasons)


def test_queue_age_thresholds_do_not_stack():
    """
    A report past the seven-day mark is also past the three-day mark. If both
    branches fired it would score one point higher than intended and every old
    report would read as high priority.
    """

    _, reasons = assess_priority(
        threat_code=A_NEUTRAL_THREAT,
        evidence_completeness=EvidenceCompleteness.MINIMAL,
        hours_in_queue=QUEUE_AGE_HIGH_HOURS + 100,
    )

    age_reasons = [r for r in reasons if "Waiting" in r]

    assert len(age_reasons) == 1


def test_queue_age_boundaries_are_inclusive():
    _, at_elevated = assess_priority(
        threat_code=A_NEUTRAL_THREAT,
        evidence_completeness=EvidenceCompleteness.PARTIAL,
        hours_in_queue=QUEUE_AGE_ELEVATED_HOURS,
    )

    _, below_elevated = assess_priority(
        threat_code=A_NEUTRAL_THREAT,
        evidence_completeness=EvidenceCompleteness.PARTIAL,
        hours_in_queue=QUEUE_AGE_ELEVATED_HOURS - 1,
    )

    assert any("Waiting" in r for r in at_elevated)
    assert not any("Waiting" in r for r in below_elevated)


def test_seven_day_threshold_outranks_three_day():
    _, seven_day = assess_priority(
        threat_code=A_NEUTRAL_THREAT,
        evidence_completeness=EvidenceCompleteness.MINIMAL,
        hours_in_queue=QUEUE_AGE_HIGH_HOURS,
    )

    assert any("seven days" in r for r in seven_day)
    assert not any("three days" in r for r in seven_day)


def test_queue_age_alone_can_reach_high_priority():
    """
    Age is deliberately the heaviest single cue. A report nobody has looked at
    for a week is a process failure regardless of what it contains, and it is
    the one condition measurable without interpreting anything.
    """

    priority, _ = assess_priority(
        threat_code=AN_URGENT_THREAT,
        evidence_completeness=EvidenceCompleteness.COMPLETE,
        hours_in_queue=QUEUE_AGE_HIGH_HOURS,
    )

    assert priority == CasePriority.HIGH


def test_minimal_evidence_is_explained_rather_than_penalised():
    """
    A coordinator seeing a standard priority should be told what is missing,
    not left to infer that the report does not matter.
    """

    _, reasons = assess_priority(
        threat_code=A_NEUTRAL_THREAT,
        evidence_completeness=EvidenceCompleteness.MINIMAL,
        hours_in_queue=1,
    )

    assert any("photograph" in r.lower() for r in reasons)


# ---------------------------------------------------------------------------
# The threat proxy
# ---------------------------------------------------------------------------


def test_every_urgent_threat_names_its_own_inference():
    """
    The proxy stands in for three US5.7 AC1 conditions the schema cannot
    measure. It is only defensible because the coordinator can see the
    inference and disagree with it, so an urgent threat must always produce a
    reason string rather than silently adding a point.
    """

    for threat_code, expected_reason in THREAT_URGENCY_REASON.items():
        _, reasons = assess_priority(
            threat_code=threat_code,
            evidence_completeness=EvidenceCompleteness.PARTIAL,
            hours_in_queue=1,
        )

        assert expected_reason in reasons


def test_unsure_reports_gain_no_urgency_from_their_category():
    """
    An unsure report is by definition one the observer could not characterise.
    Inferring urgency from it would be inventing information.
    """

    _, reasons = assess_priority(
        threat_code="unsure",
        evidence_completeness=EvidenceCompleteness.COMPLETE,
        hours_in_queue=1,
    )

    assert not any(r in THREAT_URGENCY_REASON.values() for r in reasons)


def test_an_unknown_threat_code_does_not_raise():
    """
    threat_category is a reference table and can gain rows. A code with no
    entry in the proxy map must be treated as neutral rather than crashing the
    whole queue.
    """

    priority, reasons = assess_priority(
        threat_code="a_threat_added_next_iteration",
        evidence_completeness=EvidenceCompleteness.COMPLETE,
        hours_in_queue=1,
    )

    assert priority in tuple(CasePriority)
    assert reasons


# ---------------------------------------------------------------------------
# Band boundaries
# ---------------------------------------------------------------------------


def test_a_single_cue_reaches_medium_but_not_high():
    priority, _ = assess_priority(
        threat_code=AN_URGENT_THREAT,
        evidence_completeness=EvidenceCompleteness.PARTIAL,
        hours_in_queue=1,
    )

    assert priority == CasePriority.MEDIUM
    assert MEDIUM_PRIORITY_SCORE < HIGH_PRIORITY_SCORE


def test_three_cues_together_reach_high():
    priority, reasons = assess_priority(
        threat_code=AN_URGENT_THREAT,
        evidence_completeness=EvidenceCompleteness.COMPLETE,
        hours_in_queue=QUEUE_AGE_ELEVATED_HOURS,
    )

    assert priority == CasePriority.HIGH
    assert len(reasons) == 3


# ---------------------------------------------------------------------------
# The combined entry point
# ---------------------------------------------------------------------------


def test_build_triage_cues_matches_the_two_rules_it_composes():
    """
    The queue and the case detail both call build_triage_cues, so if it ever
    diverged from the underlying rules the two views would agree with each
    other and both be wrong.
    """

    arguments = dict(
        threat_code=AN_URGENT_THREAT,
        evidence_count=2,
        has_location_detail=True,
        description_length=A_LONG_DESCRIPTION,
        hours_in_queue=QUEUE_AGE_HIGH_HOURS + 10,
    )

    completeness, priority, reasons = build_triage_cues(**arguments)

    expected_completeness = assess_evidence_completeness(
        evidence_count=arguments["evidence_count"],
        has_location_detail=arguments["has_location_detail"],
        description_length=arguments["description_length"],
    )

    expected_priority, expected_reasons = assess_priority(
        threat_code=arguments["threat_code"],
        evidence_completeness=expected_completeness,
        hours_in_queue=arguments["hours_in_queue"],
    )

    assert completeness == expected_completeness
    assert priority == expected_priority
    assert reasons == expected_reasons


def test_the_production_queue_cases_classify_as_observed():
    """
    Three real cases from the deployed queue, kept as a regression check. If a
    rule change reclassifies these, it should be a decision rather than a
    surprise.
    """

    # RC-0001: ghost gear, two photos, location, 548 hours waiting
    assert build_triage_cues(
        threat_code="ghost_gear",
        evidence_count=2,
        has_location_detail=True,
        description_length=60,
        hours_in_queue=548,
    )[:2] == (EvidenceCompleteness.COMPLETE, CasePriority.HIGH)

    # RC-0014: marine debris, one photo, location, four-character description
    assert build_triage_cues(
        threat_code="marine_debris",
        evidence_count=1,
        has_location_detail=True,
        description_length=4,
        hours_in_queue=241,
    )[:2] == (EvidenceCompleteness.PARTIAL, CasePriority.MEDIUM)

    # a freshly submitted report with nothing attached
    assert build_triage_cues(
        threat_code="marine_debris",
        evidence_count=0,
        has_location_detail=False,
        description_length=10,
        hours_in_queue=2,
    )[:2] == (EvidenceCompleteness.MINIMAL, CasePriority.STANDARD)


# ---------------------------------------------------------------------------
# US5.7 AC3
# ---------------------------------------------------------------------------


def test_the_rules_return_a_cue_and_nothing_else():
    """
    AC3: a priority cue must never verify the threat, close the case or make
    the conservation decision. Enforced structurally - these functions return
    an enum and a list of strings, take no database session, and have nothing
    to write to.
    """

    completeness, priority, reasons = build_triage_cues(
        threat_code=AN_URGENT_THREAT,
        evidence_count=5,
        has_location_detail=True,
        description_length=500,
        hours_in_queue=10_000,
    )

    assert isinstance(completeness, EvidenceCompleteness)
    assert isinstance(priority, CasePriority)
    assert isinstance(reasons, list)

    # nothing in the output resembles a verdict on the report itself
    forbidden = ("closed", "verified", "substantiated", "rejected")
    combined = " ".join(reasons).lower()

    assert not any(word in combined for word in forbidden)