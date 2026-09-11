from functools import lru_cache

from sqlalchemy import create_engine, text

from app.config import ROOT, settings


@lru_cache(maxsize=8)
def _engine(url):
    return create_engine(url, pool_pre_ping=True, connect_args={'connect_timeout': 3})


def get_engine(url=None):
    return _engine(url or settings.DATABASE_URL)


def apply_schema(engine):
    with engine.begin() as conn:
        # API and workers may start together on an empty database.
        conn.execute(text('SELECT pg_advisory_xact_lock(735120260909)'))
        for statement in (ROOT / 'db/init.sql').read_text().split(';'):
            if statement.strip():
                conn.execute(text(statement))
