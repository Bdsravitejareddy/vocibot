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
    tables = inspect(target_engine).get_table_names()
    with target_engine.begin() as connection:
        if "transcript_segments" in tables:
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(transcript_segments)"))}
            if "language_code" not in columns:
                connection.execute(text("ALTER TABLE transcript_segments ADD COLUMN language_code VARCHAR(20)"))
        if "recordings" in tables:
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(recordings)"))}
            for name, ddl in (("original_sha256", "VARCHAR(64)"), ("format", "VARCHAR(10) NOT NULL DEFAULT 'wav'"), ("size_bytes", "INTEGER NOT NULL DEFAULT 0")):
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE recordings ADD COLUMN {name} {ddl}"))
            connection.execute(text("UPDATE recordings SET original_sha256 = sha256 WHERE original_sha256 IS NULL AND format = 'wav'"))
        # Multi-user: ownership and the acting user on audit entries.
        for table, column in (("patients", "owner_id"), ("consultations", "owner_id"), ("record_updates", "actor_user_id")):
            if table in tables and column not in {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(36)"))
                if column == "owner_id":
                    connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_owner_id ON {table} ({column})"))
        if "patients" in tables:
            # Patient identifiers are unique per clinician, not clinic-wide.
            indexes = {row[1]: row[2] for row in connection.execute(text("PRAGMA index_list(patients)"))}
            if indexes.get("ix_patients_patient_identifier") == 1:
                connection.execute(text("DROP INDEX ix_patients_patient_identifier"))
                connection.execute(text("CREATE INDEX ix_patients_patient_identifier ON patients (patient_identifier)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_patients_owner_identifier ON patients (owner_id, patient_identifier)"))
        if "consultations" in tables:
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(consultations)"))}
            if "session_code" not in columns:
                connection.execute(text("ALTER TABLE consultations ADD COLUMN session_code VARCHAR(32)"))
            # Give consultations recorded before session IDs existed their own.
            from .models import new_session_code

            used = {row[0] for row in connection.execute(text("SELECT session_code FROM consultations WHERE session_code IS NOT NULL"))}
            for consultation_id, started_at in connection.execute(text("SELECT id, started_at FROM consultations WHERE session_code IS NULL")).all():
                when = _parse_timestamp(started_at)
                code = new_session_code(when)
                while code in used:
                    code = new_session_code(when)
                used.add(code)
                connection.execute(text("UPDATE consultations SET session_code = :code WHERE id = :id"), {"code": code, "id": consultation_id})
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_consultations_session_code ON consultations (session_code)"))


def _parse_timestamp(value: object):
    from datetime import datetime

    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
