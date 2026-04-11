"""Database connection management with context manager support."""

import sqlite3
from pathlib import Path


class DatabaseManager:
    """Owns the SQLite connection lifecycle.

    Usage::

        db = DatabaseManager(path)
        db.initialize()  # runs migrations

        with db.connect() as conn:
            rows = conn.execute("SELECT ...").fetchall()

        db.close()
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """Return the shared connection (create on first call)."""
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), timeout=10)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create tables and run pending migrations."""
        from sourdough.db.migrations import run_migrations

        conn = self.connect()
        run_migrations(conn, Path(__file__).parent / "schema")
        conn.commit()
