"""
Shared SQLAlchemy setup for account + settings storage.

Both auth_service.py and settings_service.py import from here rather than
each other, so they stay independently testable but share one engine, one
connection pool, and one migration path (Base.metadata.create_all below).

Replaces the old database/users/*.json and database/settings/*.json files,
which lived on Render's free-tier disk — ephemeral storage that gets wiped
on every restart or redeploy. Postgres (or any DATABASE_URL) survives that.
"""

import logging
from sqlalchemy import create_engine, Column, String, Float, Boolean, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL

logger = logging.getLogger("SCALABLE")

Base = declarative_base()

# pool_pre_ping avoids "server closed the connection unexpectedly" errors —
# Render Postgres (and most managed Postgres) can drop idle connections,
# and pre_ping transparently reconnects instead of surfacing that as a 500.
_engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    # SQLite needs this to be usable across the threads FastAPI's sync
    # route handlers/thread pool may call it from; irrelevant for Postgres.
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class UserRecord(Base):
    """One row per account. Mirrors the old database/users/<username>.json
    shape field-for-field so existing callers (auth_service.py) don't need
    to change what keys they read/write."""
    __tablename__ = "users"

    username = Column(String(30), primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    display_name = Column(String(60), nullable=False, default="")
    password_hash = Column(Text, nullable=True)  # NULL for OAuth-only accounts
    oauth = Column(JSON, nullable=False, default=dict)  # {"google": "sub_id", ...}
    created_at = Column(Float, nullable=True)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "email": self.email or "",
            "display_name": self.display_name or self.username,
            "password_hash": self.password_hash,
            "oauth": self.oauth or {},
            "created_at": self.created_at,
        }


class SettingsRecord(Base):
    """One row per account (or guest key). Mirrors the old
    database/settings/<key>.json shape / UserSettings dataclass."""
    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    display_name = Column(String(80), nullable=False, default="")
    preferred_title = Column(String(40), nullable=False, default="")
    language = Column(String(40), nullable=False, default="English")
    bio = Column(Text, nullable=False, default="")
    theme = Column(String(10), nullable=False, default="dark")
    photo_url = Column(String(500), nullable=False, default="")
    improve_model_for_everyone = Column(Boolean, nullable=False, default=True)
    marketing_measurement = Column(Boolean, nullable=False, default=True)
    personalized_marketing = Column(Boolean, nullable=False, default=True)

    def to_dict(self) -> dict:
        return {
            "display_name": self.display_name or "",
            "preferred_title": self.preferred_title or "",
            "language": self.language or "English",
            "bio": self.bio or "",
            "theme": self.theme or "dark",
            "photo_url": self.photo_url or "",
            "improve_model_for_everyone": bool(self.improve_model_for_everyone),
            "marketing_measurement": bool(self.marketing_measurement),
            "personalized_marketing": bool(self.personalized_marketing),
        }


def init_db() -> None:
    """Creates the users/settings tables if they don't exist yet. Safe to
    call on every app startup — no-op once the tables are already there."""
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.error("[DB] Could not initialize database tables: %s", e, exc_info=True)
        raise