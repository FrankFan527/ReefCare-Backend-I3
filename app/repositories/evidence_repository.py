from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_case_evidence_metadata(
    db: AsyncSession,
    report_reference: str,
):
    """
    Return safe evidence metadata for case projection.

    file_reference is deliberately excluded because private
    evidence access is handled separately.
    """

    result = await db.execute(
        text(
            """
            SELECT
                e.evidence_id,
                e.media_type,
                e.captured_at,
                e.uploaded_at

            FROM evidence e

            JOIN report r
                ON r.report_id = e.report_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL

            ORDER BY
                e.display_order,
                e.evidence_id
            """
        ),
        {
            "report_reference": report_reference,
        },
    )

    return result.mappings().all()