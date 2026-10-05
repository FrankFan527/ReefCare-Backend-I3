# ---------------------------------------------------------------------------
# US8.3 Selected external context — policy.
#
# Refresh on read, with a staleness window:
#
#   stored values newer than the window   -> return them, no provider call
#   older, or none stored                 -> call NOAA
#       NOAA answers                      -> store, return the fresh values
#       NOAA does not answer              -> return the last stored values,
#                                            with their real dates, or say
#                                            unavailable if there are none
#
# NOAA publishes once a day, so the window (24 hours by default) costs no
# freshness, and it keeps a busy page from calling the provider on every view.
#
# US8.3 AC4 is the rule this file is built around: nothing here can make the
# rest of ReefCare fail. A provider error or a database error while caching
# degrades this one response and nothing else.
# ---------------------------------------------------------------------------

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.repositories import external_context_repository as the_repository
from app.schemas.external_context import (
    ExternalContextItem,
    ExternalContextResponse,
    ExternalContextState,
)
from app.services import external_context_provider as the_provider


logger = logging.getLogger(__name__)


# the values ReefCare publishes. Sea surface temperature is deliberately not
# among them: it is the easiest number to misread as a safety signal.
THE_PUBLISHED_TYPE_CODES: list[str] = [
    the_provider.THE_DHW_CONTEXT_TYPE,
    the_provider.THE_BAA_CONTEXT_TYPE,
]


THE_MESSAGES: dict[ExternalContextState, str] = {
    ExternalContextState.AVAILABLE:
        "Satellite heat-stress context from NOAA Coral Reef Watch is shown "
        "with the date each value describes.",
    ExternalContextState.UNAVAILABLE:
        "External heat-stress context is unavailable right now. Everything "
        "else on this page is unaffected.",
    ExternalContextState.SITE_POSITION_UNAVAILABLE:
        "This site has no configured position, so external context cannot be "
        "matched to it.",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stored_values_are_fresh(
    the_rows: list[dict],
    the_now: datetime,
) -> bool:
    """
    Fresh means every published type is stored and the most recently fetched
    one is inside the staleness window.

    The window is measured on retrieval time, not on the period described:
    NOAA's own lag means the described day is always a day or two old, and
    measuring that would refetch on every request for no gain.
    """

    the_stored_types = {the_row["context_type_code"] for the_row in the_rows}

    if not set(THE_PUBLISHED_TYPE_CODES) <= the_stored_types:
        return False

    the_newest_fetch = max(the_row["retrieved_at"] for the_row in the_rows)
    the_window = timedelta(hours=settings.external_context_staleness_hours)

    return the_now - the_newest_fetch < the_window


def to_item(
    the_row: dict,
) -> ExternalContextItem:
    return ExternalContextItem(
        context_type=the_row["context_type_code"],
        label=the_row["context_type_label"],
        value=(
            float(the_row["numeric_value"])
            if the_row["numeric_value"] is not None
            else None
        ),
        display_value=the_row["display_value"],
        unit=the_row["unit"],
        represented_period_start=the_row["represented_period_start"],
        represented_period_end=the_row["represented_period_end"],
        retrieved_at=the_row["retrieved_at"],
        last_reviewed_at=the_row["last_reviewed_at"],
        provider_grid_latitude=(
            float(the_row["provider_latitude"])
            if the_row["provider_latitude"] is not None
            else None
        ),
        provider_grid_longitude=(
            float(the_row["provider_longitude"])
            if the_row["provider_longitude"] is not None
            else None
        ),
    )


async def get_external_context(
    db: AsyncSession,
    dive_site_id: int,
) -> ExternalContextResponse:
    """
    NOAA heat-stress context for one configured site. Never raises for a
    provider or caching failure; raises NotFoundError only for an unknown site.
    """

    the_site = await the_repository.get_site_position(db=db, dive_site_id=dive_site_id)

    if the_site is None:
        raise NotFoundError("Dive site not found")

    the_base = {
        "dive_site_id": the_site["dive_site_id"],
        "site_name": the_site["site_name"],
        "public_area_label": the_site["public_area_label"],
    }

    the_source = await the_repository.get_source(
        db=db,
        source_code=the_provider.PROVIDER_CODE,
    )

    if the_source is None or not the_source["is_active"]:
        return ExternalContextResponse(
            **the_base,
            state=ExternalContextState.UNAVAILABLE,
            message=THE_MESSAGES[ExternalContextState.UNAVAILABLE],
        )

    the_source_fields = {
        "source_name": the_source["name"],
        "source_url": the_source["provider_url"],
        "attribution": the_source["attribution_text"],
    }

    if the_site["centre_latitude"] is None or the_site["centre_longitude"] is None:
        # never borrow a neighbouring site's value
        return ExternalContextResponse(
            **the_base,
            **the_source_fields,
            state=ExternalContextState.SITE_POSITION_UNAVAILABLE,
            message=THE_MESSAGES[ExternalContextState.SITE_POSITION_UNAVAILABLE],
        )

    the_stored = await the_repository.list_latest_snapshots(
        db=db,
        dive_site_id=dive_site_id,
        source_id=the_source["external_context_source_id"],
        context_type_codes=THE_PUBLISHED_TYPE_CODES,
    )

    the_refresh_failed = False

    if not stored_values_are_fresh(the_stored, utc_now()):
        the_refreshed = await _refresh_from_provider(
            db=db,
            the_site=the_site,
            the_source=the_source,
        )

        if the_refreshed:
            the_stored = await the_repository.list_latest_snapshots(
                db=db,
                dive_site_id=dive_site_id,
                source_id=the_source["external_context_source_id"],
                context_type_codes=THE_PUBLISHED_TYPE_CODES,
            )

        else:
            the_refresh_failed = True

    if not the_stored:
        return ExternalContextResponse(
            **the_base,
            **the_source_fields,
            state=ExternalContextState.UNAVAILABLE,
            message=THE_MESSAGES[ExternalContextState.UNAVAILABLE],
        )

    return ExternalContextResponse(
        **the_base,
        **the_source_fields,
        state=ExternalContextState.AVAILABLE,
        message=(
            "NOAA Coral Reef Watch could not be reached just now, so the most "
            "recent stored values are shown with the dates they describe."
            if the_refresh_failed
            else THE_MESSAGES[ExternalContextState.AVAILABLE]
        ),
        items=[to_item(the_row) for the_row in the_stored],
        showing_last_stored_values=the_refresh_failed,
    )


async def _refresh_from_provider(
    db: AsyncSession,
    the_site: dict,
    the_source: dict,
) -> bool:
    """
    Fetch and store. True when fresh values were saved; False for any
    failure, which the caller answers with stored values or unavailability.
    """

    the_result = await the_provider.fetch_site_context(
        latitude=float(the_site["centre_latitude"]),
        longitude=float(the_site["centre_longitude"]),
    )

    if not the_result.available:
        return False

    try:
        await the_repository.save_snapshots(
            db=db,
            source_id=the_source["external_context_source_id"],
            dive_site_id=the_site["dive_site_id"],
            values=the_result.values,
            provider_latitude=the_result.grid_latitude,
            provider_longitude=the_result.grid_longitude,
            retrieved_at=the_result.retrieved_at,
        )

        await db.commit()

    except SQLAlchemyError:
        # a caching failure must not cost the visitor the page
        await db.rollback()

        logger.exception(
            "External context could not be cached for dive site %s",
            the_site["dive_site_id"],
        )

        return False

    return True
