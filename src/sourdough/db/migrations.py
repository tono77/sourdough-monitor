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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] > 0


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    return column in cols


def _detect_existing_schema(conn: sqlite3.Connection) -> int:
    """Detect how far the old inline-migration schema got.

    The original db.py applied migrations via ALTER TABLE without tracking
    versions.  This function checks which columns exist to determine the
    equivalent schema version so we can mark them as already applied.
    """
    if not _table_exists(conn, "sesiones"):
        return 0  # fresh database

    # Migration 003: mediciones has altura_y_pct
    if _column_exists(conn, "mediciones", "altura_y_pct"):
        return 3

    # Migration 002: sesiones has fondo_y_pct
    if _column_exists(conn, "sesiones", "fondo_y_pct"):
        return 2

    # Migration 001: tables exist
    return 1


def run_migrations(conn: sqlite3.Connection, schema_dir: Path) -> None:
    """Apply any pending .sql migrations from *schema_dir*."""
    _ensure_version_table(conn)
    current = _current_version(conn)

    # For existing databases created by the old init_db() (inline ALTER TABLE
    # without version tracking), detect which migrations are already applied
    # by inspecting the actual schema, and mark them as done.
    detected = _detect_existing_schema(conn)
    if detected > current:
        log.info(
            "Existing schema detected at level %d (tracked: %d) — recording",
            detected, current,
        )
        for v in range(1, detected + 1):
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (v,)
            )
        conn.commit()
        current = detected

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
