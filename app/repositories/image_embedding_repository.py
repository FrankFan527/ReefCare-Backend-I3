"""Internal Observer photo inputs and cached features; never exposed by an API."""

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_image_inputs(db: AsyncSession, report_ids: list[int], per_report_limit: int = 8) -> list[dict]:
    if not report_ids:
        return []
    result = await db.execute(text("""
        WITH photos AS (
            SELECT e.evidence_id, e.report_id, e.file_reference, e.uploaded_at,
                   e.image_embedding, e.image_embedding_model,
                   e.image_embedding_version, e.image_embedding_generated_at,
                   row_number() OVER (PARTITION BY e.report_id
                       ORDER BY e.uploaded_at DESC, e.evidence_id DESC) AS image_rank
            FROM evidence e
            JOIN report r ON r.report_id=e.report_id
            JOIN case_status cs ON cs.case_status_id=r.current_status_id
            LEFT JOIN case_event ce ON ce.case_event_id=e.case_event_id
            WHERE e.report_id IN :report_ids AND e.media_type='photo'
              AND r.deleted_at IS NULL AND cs.code NOT IN ('draft','submitted')
              AND (e.case_event_id IS NULL OR ce.event_type='info_provided')
        )
        SELECT evidence_id,report_id,file_reference,uploaded_at,image_embedding,
               image_embedding_model,image_embedding_version,image_embedding_generated_at
        FROM photos WHERE image_rank <= :image_limit
        ORDER BY report_id,evidence_id
    """).bindparams(bindparam("report_ids", expanding=True)),
        {"report_ids": sorted(set(report_ids)), "image_limit": max(1, min(per_report_limit, 20))})
    return [dict(row) for row in result.mappings().all()]


async def save_embedding(db: AsyncSession, evidence_id: int, file_reference: str,
                         vector: tuple[float, ...], model: str, version: str) -> bool:
    """Compare the private object key to avoid caching features for a replaced file.

    The normal evidence model treats files as immutable; this guard also protects
    an administrative replacement during generation. Never modify file metadata.
    """
    result = await db.execute(text("""
        UPDATE evidence e SET image_embedding=CAST(:vector AS real[]),
            image_embedding_model=:model,image_embedding_version=:version,
            image_embedding_generated_at=clock_timestamp()
        FROM report r,case_status cs
        WHERE e.evidence_id=:evidence_id AND e.file_reference=:file_reference
          AND e.report_id=r.report_id AND r.current_status_id=cs.case_status_id
          AND r.deleted_at IS NULL AND cs.code NOT IN ('draft','submitted')
          AND e.media_type='photo'
          AND (e.case_event_id IS NULL OR EXISTS (
              SELECT 1 FROM case_event ce WHERE ce.case_event_id=e.case_event_id
                  AND ce.event_type='info_provided'))
        RETURNING e.evidence_id
    """), {"evidence_id": evidence_id, "file_reference": file_reference,
            "vector": list(vector), "model": model, "version": version})
    return result.scalar_one_or_none() is not None


async def list_eligible_report_references(db: AsyncSession, after_report_id: int = 0, limit: int = 100) -> list[dict]:
    """Keyset scan for a durable worker/backfill, including reports without runs."""
    result = await db.execute(text("""
        SELECT r.report_id,r.report_reference FROM report r
        JOIN case_status cs ON cs.case_status_id=r.current_status_id
        WHERE r.report_id > :after_id AND r.deleted_at IS NULL
          AND cs.code NOT IN ('draft','submitted')
        ORDER BY r.report_id LIMIT :limit
    """), {"after_id": after_report_id, "limit": max(1, min(limit, 500))})
    return [dict(row) for row in result.mappings().all()]
