"""Simple versioned migration runner.

Tracks applied migrations in a ``schema_version`` table.
Each numbered ``.sql`` file in the schema directory is applied in order.
"""

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    return row[0]


def run_migrations(conn: sqlite3.Connection, schema_dir: Path) -> None:
    """Apply any pending .sql migrations from *schema_dir*."""
    _ensure_version_table(conn)
    current = _current_version(conn)

    # Collect migration files sorted by number
    migration_files: list[tuple[int, Path]] = []
    for sql_file in sorted(schema_dir.glob("*.sql")):
        # Expect filenames like 001_initial.sql
        try:
            version = int(sql_file.stem.split("_", 1)[0])
        except ValueError:
            continue
        migration_files.append((version, sql_file))

    applied = 0
    for version, sql_file in migration_files:
        if version <= current:
            continue
        log.info("Applying migration %s", sql_file.name)
        sql = sql_file.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.commit()
        applied += 1

    if applied:
        log.info("Applied %d migration(s), now at version %d", applied, _current_version(conn))
