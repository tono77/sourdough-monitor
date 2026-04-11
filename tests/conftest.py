"""Shared test fixtures."""

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def db_conn():
    """In-memory SQLite with the full schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # Apply all migrations in order
    schema_dir = Path(__file__).resolve().parent.parent / "src" / "sourdough" / "db" / "schema"
    for sql_file in sorted(schema_dir.glob("*.sql")):
        conn.executescript(sql_file.read_text())

    # Add schema_version table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    for sql_file in sorted(schema_dir.glob("*.sql")):
        version = int(sql_file.stem.split("_", 1)[0])
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()

    yield conn
    conn.close()
