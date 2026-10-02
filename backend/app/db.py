from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def migrate_sqlite_schema(target_engine=engine) -> None:
    """Apply small backwards-compatible SQLite column additions for local app data."""

    if target_engine.dialect.name != "sqlite":
        return
    if "transcript_segments" not in inspect(target_engine).get_table_names():
        return
    with target_engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(transcript_segments)"))}
        if "language_code" not in columns:
            connection.execute(text("ALTER TABLE transcript_segments ADD COLUMN language_code VARCHAR(20)"))


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
