#!/usr/bin/env python3
"""Migrate an existing fermento.db to the new versioned schema.

Reads the existing database, applies any pending migrations, and migrates
orphaned measurements into a historical session.

Usage:
    python scripts/migrate_db.py [path/to/fermento.db]
"""

import sys
from pathlib import Path

# Add src to path so we can import sourdough
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sourdough.db.connection import DatabaseManager
from sourdough.db.repository import migrate_historical_data
from sourdough.log import setup_logging


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/fermento.db")

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    setup_logging(Path("data/sourdough.log"))

    print(f"Migrating {db_path} ...")
    db = DatabaseManager(db_path)
    db.initialize()

    conn = db.connect()
    migrate_historical_data(conn)

    # Verify
    version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    sessions = conn.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0]
    measurements = conn.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]

    print(f"Schema version: {version}")
    print(f"Sessions: {sessions}")
    print(f"Measurements: {measurements}")
    print("Migration complete.")

    db.close()


if __name__ == "__main__":
    main()
