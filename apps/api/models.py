"""SQLAlchemy Core model registry reflected from the exact application schema."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.engine import Engine

metadata = MetaData()


def refresh_metadata(engine: Engine) -> MetaData:
    metadata.clear()
    metadata.reflect(bind=engine)
    return metadata
