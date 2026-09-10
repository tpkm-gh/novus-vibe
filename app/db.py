"""Engine/session setup.

Defaults to an on-disk SQLite file when USE_SQLITE_FALLBACK=1 (the .env.example
default) so `uvicorn app.main:app` works with zero infrastructure. Flip that
flag off and point DATABASE_URL at Postgres (docker-compose.yml ships one)
for anything beyond a laptop demo -- see docs/PLAYBOOK.md, "Scaling &
future-proofing".

The schema (app/models.py) intentionally avoids Postgres-only column types
(UUID, JSONB) so the same models run unmodified against both engines. That's
a deliberate scope cut for the prototype, not an accident -- named in the
playbook rather than hidden.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    if settings.use_sqlite_fallback:
        return create_engine(
            "sqlite:///./novus_vibe.db",
            connect_args={"check_same_thread": False},
        )
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from . import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()
