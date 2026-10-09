from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


# DATABASE_URL is expected to point at the Neon pooled endpoint
# (the "-pooler" host, PgBouncer in transaction mode), so each new
# serverless instance reuses Neon's warm Postgres backends instead of
# opening a fresh direct connection.
#
# prepare_threshold=None turns off psycopg server-side prepared
# statements. In transaction pooling, consecutive statements can land on
# different backends, so a statement prepared on one backend must never
# be reused on another.
#
# Only pg_advisory_xact_lock (transaction-scoped) is used in the codebase,
# which is safe under transaction pooling.
the_psycopg_connect_arguments: dict = {
    "prepare_threshold": None,
}


engine = create_async_engine(
    settings.database_url,
    # check the connection is alive before handing it out,
    # Neon can close idle connections after compute autosuspend
    pool_pre_ping=True,
    # retire connections before Neon/PgBouncer idle timeouts drop them,
    # so a request never waits on a dead socket and a reconnect
    pool_recycle=300,
    # small pool, a serverless instance only serves a few requests at once
    pool_size=5,
    max_overflow=5,
    # fail fast with an error instead of hanging when the pool is exhausted
    pool_timeout=10,
    connect_args=the_psycopg_connect_arguments,
)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session():
    async with AsyncSessionLocal() as session:
        yield session
