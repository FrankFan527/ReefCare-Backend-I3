# ---------------------------------------------------------------------------
# US8.3 selected external context — persistence.
#
# Reads and writes external_context_snapshot, which the E8 migration created
# with no link to report, case_decision or evidence. Nothing in this file can
# join external context to a case, because US8.3 AC3 says it may never verify,
# reject, prioritise or close one.
# ---------------------------------------------------------------------------

from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.external_context_provider import ProviderValue


async def get_site_position(
    db: AsyncSession,
    dive_site_id: int,
) -> dict | None:
    """
    The configured site and its published centre. A dive site centre is
    public reference data, not a report location.
    """

    the_result = await db.execute(
        text(
            """
            SELECT dive_site_id, name AS site_name, public_area_label,
                   centre_latitude, centre_longitude
            FROM dive_site
            WHERE dive_site_id = :dive_site_id
            """
        ),
        {"dive_site_id": dive_site_id},
    )

    the_row = the_result.mappings().first()

    return dict(the_row) if the_row is not None else None


async def get_source(
    db: AsyncSession,
    source_code: str,
) -> dict | None:
    the_result = await db.execute(
        text(
            """
            SELECT external_context_source_id, code, name, attribution_text,
                   provider_url, licence_note, update_cadence, is_active,
                   last_reviewed_at
            FROM external_context_source
            WHERE code = :source_code
            """
        ),
        {"source_code": source_code},
    )

    the_row = the_result.mappings().first()

    return dict(the_row) if the_row is not None else None


async def list_latest_snapshots(
    db: AsyncSession,
    dive_site_id: int,
    source_id: int,
    context_type_codes: list[str],
) -> list[dict]:
    """
    The newest stored value of each requested type for one site, judged by
    the period it describes rather than when it was fetched.
    """

    the_result = await db.execute(
        text(
            """
            SELECT DISTINCT ON (t.code)
                t.code         AS context_type_code,
                t.label        AS context_type_label,
                t.unit,
                t.display_order,
                s.numeric_value,
                s.display_value,
                s.represented_period_start,
                s.represented_period_end,
                s.provider_latitude,
                s.provider_longitude,
                s.retrieved_at,
                s.last_reviewed_at
            FROM external_context_snapshot AS s
            JOIN external_context_type AS t
              ON t.external_context_type_id = s.external_context_type_id
            WHERE s.dive_site_id = :dive_site_id
              AND s.external_context_source_id = :source_id
              AND t.code IN :type_codes
            ORDER BY t.code, s.represented_period_end DESC, s.retrieved_at DESC
            """
        ).bindparams(bindparam("type_codes", expanding=True)),
        {
            "dive_site_id": dive_site_id,
            "source_id": source_id,
            "type_codes": context_type_codes,
        },
    )

    the_rows = [dict(the_row) for the_row in the_result.mappings().all()]

    the_rows.sort(key=lambda the_row: (the_row["display_order"], the_row["context_type_code"]))

    return the_rows


async def save_snapshots(
    db: AsyncSession,
    source_id: int,
    dive_site_id: int,
    values: list[ProviderValue],
    provider_latitude: float | None,
    provider_longitude: float | None,
    retrieved_at: datetime,
) -> int:
    """
    Store one fetch. Re-fetching a period already held replaces that row
    rather than adding a duplicate, through the table's unique key on
    (source, type, site, period end).

    The validation trigger on the table refuses an inactive source or type,
    and any period ending in the future.
    """

    the_saved = 0

    for the_value in values:
        the_result = await db.execute(
            text(
                """
                INSERT INTO external_context_snapshot
                    (external_context_source_id, external_context_type_id,
                     dive_site_id, numeric_value, display_value,
                     represented_period_start, represented_period_end,
                     provider_latitude, provider_longitude, retrieved_at)
                SELECT
                    :source_id, t.external_context_type_id,
                    :dive_site_id, :numeric_value, :display_value,
                    :represented_date, :represented_date,
                    :provider_latitude, :provider_longitude, :retrieved_at
                FROM external_context_type AS t
                WHERE t.code = :context_type_code
                ON CONFLICT (external_context_source_id, external_context_type_id,
                             dive_site_id, represented_period_end)
                DO UPDATE SET
                    numeric_value      = EXCLUDED.numeric_value,
                    display_value      = EXCLUDED.display_value,
                    provider_latitude  = EXCLUDED.provider_latitude,
                    provider_longitude = EXCLUDED.provider_longitude,
                    retrieved_at       = EXCLUDED.retrieved_at
                """
            ),
            {
                "source_id": source_id,
                "dive_site_id": dive_site_id,
                "numeric_value": the_value.numeric_value,
                "display_value": the_value.display_value,
                "represented_date": the_value.represented_date,
                "provider_latitude": provider_latitude,
                "provider_longitude": provider_longitude,
                "retrieved_at": retrieved_at,
                "context_type_code": the_value.context_type_code,
            },
        )

        the_saved += the_result.rowcount or 0

    return the_saved
