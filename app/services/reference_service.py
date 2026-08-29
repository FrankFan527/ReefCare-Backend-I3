# ---------------------------------------------------------------------------
# Reference data workflow (US4.1).
#
# Thin by design. The dive site list has no policy attached to it today, but
# the boundary is Route -> Service -> Repository -> PostgreSQL, and a route
# that reaches past the service breaks that for everyone reading the codebase.
# When a rule does appear here, there is already a place for it.
# ---------------------------------------------------------------------------
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.reference_repository import list_active_dive_sites


async def get_dive_sites(db: AsyncSession) -> list:
    """
    Return the named dive sites an observer may select from.

    Read-only, so no transaction handling is needed.
    """

    return await list_active_dive_sites(db=db)