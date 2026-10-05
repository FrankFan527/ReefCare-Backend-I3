"""Retry/backfill explicitly selected report references using the normal engine."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.services.related_incident_detection_service import run_related_incident_detection


async def main(references, force=False, generate_embeddings=False):
    failed = False
    for reference in references:
        async with AsyncSessionLocal() as db:
            state = await run_related_incident_detection(db, reference, force=force, generate_embeddings=generate_embeddings)
        print(f"{reference}: {state.value if state else 'ineligible'}")
        failed |= state is not None and state.value == "failed"
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_references", nargs="+")
    parser.add_argument("--force", action="store_true", help="Recompute even when the input fingerprint is unchanged")
    parser.add_argument("--generate-embeddings", action="store_true", help="Requires optional image dependencies and installed weights")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.report_references, args.force, args.generate_embeddings)))
