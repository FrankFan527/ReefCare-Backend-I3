"""Durable periodic recovery/backfill: cache photos first, then analyse reports.

Run as a persistent backend process; --once makes an explicit one-shot backfill.
No public job endpoint, and no report claims or relationship decisions.
"""
import argparse
import asyncio
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.repositories import image_embedding_repository as repository
from app.services.image_embedding_service import generate_missing_embeddings, _load_model
from app.services.related_incident_detection_service import run_related_incident_detection

logger = logging.getLogger(__name__)


async def references(batch_size):
    after_id = 0
    while True:
        async with AsyncSessionLocal() as db:
            rows = await repository.list_eligible_report_references(db, after_id, batch_size)
        if not rows:
            return
        for row in rows:
            yield row
        after_id = rows[-1]["report_id"]


async def sweep(batch_size=100, cached_only=False):
    failed = False
    if settings.related_incident_images_enabled and not cached_only:
        async for row in references(batch_size):
            async with AsyncSessionLocal() as db:
                try:
                    photos = await repository.list_image_inputs(db, [row["report_id"]], settings.related_incident_images_per_report)
                    try:
                        async with asyncio.timeout(settings.related_incident_timeout_seconds/2):
                            await generate_missing_embeddings(db, photos)
                    except TimeoutError:
                        logger.warning("Photo generation budget exhausted for %s", row["report_reference"])
                    await db.commit()
                except Exception as error:
                    failed = True
                    await db.rollback()
                    logger.warning("Photo caching failed for %s (%s)", row["report_reference"], type(error).__name__)
    # Separate pass ensures every historical source has had a caching opportunity
    # before older reports are compared to newly submitted reports' photos.
    async for row in references(batch_size):
        async with AsyncSessionLocal() as db:
            state = await run_related_incident_detection(db, row["report_reference"], generate_embeddings=False)
        logger.info("%s: %s", row["report_reference"], state.value if state else "ineligible")
        failed |= state is not None and state.value == "failed"
    return int(failed)


async def main(args):
    if settings.related_incident_images_enabled and not args.cached_only:
        try:
            await asyncio.to_thread(_load_model,settings.related_incident_image_weights_path)
        except Exception as error:
            logger.error("Image worker could not load pretrained model (%s). Install requirements-image.txt and prepare weights, or use --cached-only.",type(error).__name__)
            return 1
    while True:
        try:
            result = await sweep(args.batch_size, args.cached_only)
        except Exception as error:
            logger.warning("Related incident worker sweep failed (%s)", type(error).__name__)
            result = 1
        if args.once:
            return result
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--cached-only", action="store_true", help="Recover matching without generating image features")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 500 or args.interval < 10:
        parser.error("batch-size must be 1..500 and interval at least 10 seconds")
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main(args)))
