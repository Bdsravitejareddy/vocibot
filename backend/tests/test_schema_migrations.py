from sqlalchemy import create_engine, inspect, text

from app.db import migrate_sqlite_schema


def test_sqlite_migration_adds_language_code_without_losing_transcript_rows() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE transcript_segments (id TEXT PRIMARY KEY, text TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO transcript_segments (id, text) VALUES ('segment-1', 'నమస్కారం')"))

    migrate_sqlite_schema(engine)

    columns = {column["name"]: column for column in inspect(engine).get_columns("transcript_segments")}
    assert columns["language_code"]["nullable"] is True
    with engine.connect() as connection:
        row = connection.execute(text("SELECT id, text, language_code FROM transcript_segments WHERE id='segment-1'")).one()
    assert row == ("segment-1", "నమస్కారం", None)


def test_sqlite_migration_assigns_unique_session_codes_to_existing_consultations() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE consultations (id TEXT PRIMARY KEY, started_at TEXT)"))
        connection.execute(text("INSERT INTO consultations (id, started_at) VALUES ('c1', '2026-10-01 09:15:00'), ('c2', '2026-10-02 12:33:02.125766')"))

    migrate_sqlite_schema(engine)
    migrate_sqlite_schema(engine)  # idempotent

    with engine.connect() as connection:
        codes = dict(connection.execute(text("SELECT id, session_code FROM consultations")).all())
    assert codes["c1"].startswith("VB-20261001-") and codes["c2"].startswith("VB-20261002-")
    assert len(set(codes.values())) == 2
    assert all(len(code) == len("VB-20261001-") + 6 for code in codes.values())


def test_sqlite_migration_adds_recording_format_columns_and_keeps_the_original_fingerprint() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE recordings (id TEXT PRIMARY KEY, file_path TEXT, sha256 TEXT)"))
        connection.execute(text("INSERT INTO recordings (id, file_path, sha256) VALUES ('r1', '/x/VB-1.wav', 'abc')"))

    migrate_sqlite_schema(engine)

    with engine.connect() as connection:
        row = connection.execute(text("SELECT format, size_bytes, original_sha256 FROM recordings WHERE id='r1'")).one()
    assert row == ("wav", 0, "abc")
