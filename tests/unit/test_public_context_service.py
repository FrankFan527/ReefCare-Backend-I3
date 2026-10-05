# ---------------------------------------------------------------------------
# US8.2 / US2.4 public-safe site context — unit tests (no database).
#
# These are mostly tests about what must NOT come out: no private field, no
# unreviewed claim presented as a finding, and no wording that could be read
# as a statement about the reef rather than about what has been reported.
# ---------------------------------------------------------------------------

from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.schemas.public_context import PublicContextState
from app.services import public_context_service as the_service


# wording that would turn a coverage statement into a safety claim (AC6)
THE_FORBIDDEN_WORDS: tuple[str, ...] = (
    "safe", "unsafe", "threat-free", "no threats", "healthy", "clear",
    "pristine", "unaffected",
)

# fields that must never reach a public caller (AC3)
THE_FORBIDDEN_FIELDS: tuple[str, ...] = (
    "report_reference", "reportreference", "observer", "description",
    "evidence", "latitude", "longitude", "coordinator", "closure", "notes",
    "decision_note", "claimed_by",
)


def patch_repository(
    monkeypatch,
    the_threats=None,
    the_activity=None,
    the_counts=None,
):
    monkeypatch.setattr(
        the_service.the_repository, "get_public_site_identity",
        AsyncMock(return_value={
            "dive_site_id": 13,
            "site_name": "Temple of the Sea",
            "public_area_label": "Perhentian Islands",
        }),
    )
    monkeypatch.setattr(
        the_service.the_repository, "summarise_accepted_threats",
        AsyncMock(return_value=the_threats or []),
    )
    monkeypatch.setattr(
        the_service.the_repository, "list_publishable_activity",
        AsyncMock(return_value=the_activity or []),
    )
    monkeypatch.setattr(
        the_service.the_repository, "count_observations_by_assessment",
        AsyncMock(return_value=the_counts or {
            "accepted_observations": 0,
            "observations_under_review": 0,
        }),
    )


def make_threat(the_count: int = 3, the_month: str = "2026-08") -> dict:
    return {
        "threat_category_code": "ghost_gear",
        "threat_category_label": "Ghost fishing gear",
        "accepted_report_count": the_count,
        "most_recent_month": the_month,
    }


def make_activity() -> dict:
    return {
        "activity_id": 7,
        "activity_type": "debris_cleanup",
        "title": "Debris collection dive",
        "summary": "Loose debris was collected from the sandy areas.",
        "activity_date": date(2026, 7, 2),
        "source_label": "ReefCare MY",
    }


# ---------------------------------------------------------------------------
# AC4 / AC6 — the empty state is about coverage, not the reef
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_eligible_information_returns_no_public_context(monkeypatch):
    patch_repository(monkeypatch)

    the_response = await the_service.get_public_site_context(AsyncMock(), 13)

    assert the_response.state == PublicContextState.NO_PUBLIC_CONTEXT
    assert the_response.threats == []
    assert the_response.activity == []

    the_message = the_response.message.lower()

    for the_word in THE_FORBIDDEN_WORDS:
        assert the_word not in the_message

    assert "not a statement about the condition of the reef" in the_message


@pytest.mark.asyncio
async def test_the_interpretation_note_travels_with_a_populated_response(monkeypatch):
    patch_repository(monkeypatch, the_threats=[make_threat()])

    the_response = await the_service.get_public_site_context(AsyncMock(), 13)

    assert the_response.state == PublicContextState.AVAILABLE
    assert "not evidence that a site is safe" in the_response.interpretation_note.lower()


# ---------------------------------------------------------------------------
# AC2 — only reviewed observations become a named threat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reports_under_review_are_counted_but_never_named(monkeypatch):
    patch_repository(
        monkeypatch,
        the_counts={"accepted_observations": 0, "observations_under_review": 4},
    )

    the_response = await the_service.get_public_site_context(AsyncMock(), 13)

    # the count is honest
    assert the_response.assessment_summary.observations_under_review == 4

    # but an unreviewed report is not a finding, so no category is named
    assert the_response.threats == []
    assert the_response.state == PublicContextState.NO_PUBLIC_CONTEXT


@pytest.mark.asyncio
async def test_recency_stays_at_month_precision(monkeypatch):
    patch_repository(monkeypatch, the_threats=[make_threat(the_month="2026-08")])

    the_response = await the_service.get_public_site_context(AsyncMock(), 13)

    the_recency = the_response.threats[0].most_recent_month

    assert the_recency == "2026-08"
    # an exact day at a quiet site could identify one dive, and one diver
    assert len(the_recency) == 7


@pytest.mark.asyncio
async def test_a_category_below_the_threshold_is_not_published(monkeypatch):
    patch_repository(monkeypatch, the_threats=[make_threat(the_count=1)])

    monkeypatch.setattr(
        the_service, "THE_MINIMUM_ACCEPTED_REPORTS_PER_CATEGORY", 2
    )

    the_response = await the_service.get_public_site_context(AsyncMock(), 13)

    assert the_response.threats == []
    assert the_response.state == PublicContextState.NO_PUBLIC_CONTEXT


# ---------------------------------------------------------------------------
# AC3 — nothing private reaches the payload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_payload_contains_no_private_field(monkeypatch):
    patch_repository(
        monkeypatch,
        the_threats=[make_threat()],
        the_activity=[make_activity()],
        the_counts={"accepted_observations": 3, "observations_under_review": 1},
    )

    the_response = await the_service.get_public_site_context(AsyncMock(), 13)

    the_payload = the_response.model_dump(by_alias=True)

    # the two fixed sentences are excluded from the scan: the interpretation
    # note legitimately contains the word "evidence", in "it is not evidence
    # that a site is safe". Everything that carries data is scanned.
    the_payload.pop("interpretationNote", None)
    the_payload.pop("message", None)

    the_scanned = str(the_payload).lower()

    for the_field in THE_FORBIDDEN_FIELDS:
        assert the_field not in the_scanned


@pytest.mark.asyncio
async def test_published_activity_keeps_its_curated_identifier(monkeypatch):
    patch_repository(monkeypatch, the_activity=[make_activity()])

    the_response = await the_service.get_public_site_context(AsyncMock(), 13)

    assert the_response.activity[0].activity_id == 7
    assert the_response.activity[0].activity_type == "debris_cleanup"


@pytest.mark.asyncio
async def test_unknown_site_is_not_found(monkeypatch):
    monkeypatch.setattr(
        the_service.the_repository, "get_public_site_identity",
        AsyncMock(return_value=None),
    )

    with pytest.raises(NotFoundError):
        await the_service.get_public_site_context(AsyncMock(), 999)


# ---------------------------------------------------------------------------
# AC5 — E2 reuses this boundary rather than keeping its own
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_compatibility_endpoint_reads_the_shared_rule(monkeypatch):
    from app.services import public_service

    the_shared_call = AsyncMock(return_value=[])

    monkeypatch.setattr(
        public_service, "get_public_site",
        AsyncMock(return_value={
            "dive_site_id": 13,
            "name": "Temple of the Sea",
            "public_area_label": "Perhentian Islands",
        }),
    )
    monkeypatch.setattr(
        public_service, "list_publishable_activity_entries", the_shared_call
    )

    await public_service.get_public_activity(db=AsyncMock(), dive_site_id=13)

    the_shared_call.assert_awaited_once()

    # the Iteration 2 contract carries a curated activity id, so that
    # endpoint stays on curated sources
    assert the_shared_call.await_args.kwargs["include_follow_ups"] is False
