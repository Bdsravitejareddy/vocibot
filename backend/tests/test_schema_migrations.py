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
