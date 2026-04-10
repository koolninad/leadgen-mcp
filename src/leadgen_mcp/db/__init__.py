"""Database layer — routes to PostgreSQL or SQLite based on config.

If DATABASE_URL is set, uses asyncpg (pg_repository).
Otherwise, falls back to aiosqlite (repository).
"""

from ..config import settings

if settings.database_url:
    from .pg_repository import *  # noqa: F401,F403
else:
    from .repository import *  # noqa: F401,F403
