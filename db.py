#!/usr/bin/env python3
"""
Sourdough Monitor — Database module
Manages SQLite database with session support for fermentation tracking.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, date

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "fermento.db"


def get_connection():
    """Get a database connection with WAL mode and row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database schema with sessions and measurements tables."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sesiones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fin TEXT,
            estado TEXT DEFAULT 'activa',
            num_mediciones INTEGER DEFAULT 0,
            peak_nivel REAL,
            peak_timestamp TEXT,
            notas TEXT
        );

        CREATE TABLE IF NOT EXISTS mediciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id INTEGER REFERENCES sesiones(id),
            timestamp TEXT NOT NULL,
            foto_path TEXT NOT NULL,
            nivel_pct REAL,
            nivel_px INTEGER,
            burbujas TEXT,
            textura TEXT,
            notas TEXT,
            es_peak INTEGER DEFAULT 0
        );
    """)
    conn.commit()

    # Migrate: add sesion_id column if missing (for old data)
    try:
        conn.execute("SELECT sesion_id FROM mediciones LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE mediciones ADD COLUMN sesion_id INTEGER REFERENCES sesiones(id)")
        conn.commit()

    return conn


def migrate_historical_data(conn):
    """Migrate old measurements (without sesion_id) into a historical session."""
    orphans = conn.execute(
        "SELECT COUNT(*) FROM mediciones WHERE sesion_id IS NULL"
    ).fetchone()[0]

    if orphans == 0:
        return

    # Create a historical session for orphaned measurements
    first = conn.execute(
        "SELECT timestamp FROM mediciones WHERE sesion_id IS NULL ORDER BY id ASC LIMIT 1"
    ).fetchone()
    last = conn.execute(
        "SELECT timestamp FROM mediciones WHERE sesion_id IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if first and last:
        fecha = first[0][:10]  # Extract date from ISO timestamp
        cursor = conn.execute(
            "INSERT INTO sesiones (fecha, hora_inicio, hora_fin, estado, notas) VALUES (?, ?, ?, 'completada', 'Sesión histórica migrada')",
            (fecha, first[0], last[0])
        )
        session_id = cursor.lastrowid
        conn.execute(
            "UPDATE mediciones SET sesion_id = ? WHERE sesion_id IS NULL",
            (session_id,)
        )
        # Update measurement count
        count = conn.execute(
            "SELECT COUNT(*) FROM mediciones WHERE sesion_id = ?", (session_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE sesiones SET num_mediciones = ? WHERE id = ?",
            (count, session_id)
        )
        conn.commit()
        print(f"📦 Migrated {orphans} historical measurements into session #{session_id}")


def get_or_create_session(conn):
    """Get today's active session or create a new one."""
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT * FROM sesiones WHERE fecha = ? AND estado = 'activa'", (today,)
    ).fetchone()

    if row:
        return dict(row)

    now = datetime.now().isoformat()
    cursor = conn.execute(
        "INSERT INTO sesiones (fecha, hora_inicio, estado) VALUES (?, ?, 'activa')",
        (today, now)
    )
    conn.commit()
    session_id = cursor.lastrowid
    print(f"🆕 New session #{session_id} created for {today}")
    return dict(conn.execute("SELECT * FROM sesiones WHERE id = ?", (session_id,)).fetchone())


def close_session(conn, session_id):
    """Close a session and update its stats."""
    now = datetime.now().isoformat()
    count = conn.execute(
        "SELECT COUNT(*) FROM mediciones WHERE sesion_id = ?", (session_id,)
    ).fetchone()[0]

    # Find peak
    peak_row = conn.execute(
        "SELECT nivel_pct, timestamp FROM mediciones WHERE sesion_id = ? AND nivel_pct IS NOT NULL ORDER BY nivel_pct DESC LIMIT 1",
        (session_id,)
    ).fetchone()

    peak_nivel = peak_row[0] if peak_row else None
    peak_ts = peak_row[1] if peak_row else None

    conn.execute("""
        UPDATE sesiones SET hora_fin = ?, estado = 'completada',
        num_mediciones = ?, peak_nivel = ?, peak_timestamp = ?
        WHERE id = ?
    """, (now, count, peak_nivel, peak_ts, session_id))
    conn.commit()
    print(f"✅ Session #{session_id} closed with {count} measurements")


def save_measurement(conn, session_id, photo_path, analysis):
    """Save a new measurement to the database."""
    timestamp = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO mediciones (sesion_id, timestamp, foto_path, nivel_pct, nivel_px, burbujas, textura, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        timestamp,
        str(photo_path),
        analysis.get("nivel_pct"),
        analysis.get("nivel_px"),
        analysis.get("burbujas"),
        analysis.get("textura"),
        analysis.get("notas")
    ))
    # Update session measurement count
    conn.execute(
        "UPDATE sesiones SET num_mediciones = num_mediciones + 1 WHERE id = ?",
        (session_id,)
    )
    conn.commit()
    return timestamp


def detect_peak(conn, session_id):
    """Detect fermentation peak (first descent after meaningful growth from baseline).
    Requires 2 consecutive declining readings to avoid triggering on measurement noise."""
    rows = conn.execute("""
        SELECT id, nivel_pct, timestamp FROM mediciones
        WHERE sesion_id = ? AND nivel_pct IS NOT NULL
        ORDER BY id DESC LIMIT 5
    """, (session_id,)).fetchall()

    if len(rows) < 3:
        return False, None

    curr  = rows[0]  # latest
    prev  = rows[1]
    prev2 = rows[2]  # two readings ago

    # Check if peak already detected for this session
    peak_exists = conn.execute(
        "SELECT COUNT(*) FROM mediciones WHERE sesion_id = ? AND es_peak = 1",
        (session_id,)
    ).fetchone()[0]

    if peak_exists:
        return False, None

    # Get baseline (first valid measurement of this session)
    first = conn.execute("""
        SELECT nivel_pct FROM mediciones
        WHERE sesion_id = ? AND nivel_pct IS NOT NULL
        ORDER BY id ASC LIMIT 1
    """, (session_id,)).fetchone()

    if not first:
        return False, None

    baseline = first[0]

    # Get the maximum level reached so far in this session
    max_reached = conn.execute("""
        SELECT MAX(nivel_pct) FROM mediciones
        WHERE sesion_id = ? AND nivel_pct IS NOT NULL
    """, (session_id,)).fetchone()[0] or baseline

    MIN_GROWTH  = 10   # must have grown at least 10 raw units from baseline
    MIN_DECLINE = 3    # each decline step must be at least 3 units (not just noise)

    # Peak: TWO consecutive declines of meaningful magnitude AND had real growth from baseline
    two_consec_declines = (
        curr[1] < prev[1] and
        prev[1] < prev2[1] and
        (prev2[1] - curr[1]) >= MIN_DECLINE
    )

    if two_consec_declines and (max_reached - baseline) >= MIN_GROWTH:
        # Mark the actual maximum measurement as the peak (not necessarily prev2)
        max_row = conn.execute("""
            SELECT id, nivel_pct, timestamp FROM mediciones
            WHERE sesion_id = ? AND nivel_pct IS NOT NULL
            ORDER BY nivel_pct DESC LIMIT 1
        """, (session_id,)).fetchone()

        conn.execute("UPDATE mediciones SET es_peak = 1 WHERE id = ?", (max_row[0],))
        conn.execute(
            "UPDATE sesiones SET peak_nivel = ?, peak_timestamp = ? WHERE id = ?",
            (max_row[1], max_row[2], session_id)
        )
        conn.commit()
        return True, {"nivel": max_row[1], "timestamp": max_row[2]}

    return False, None


def get_session_measurements(conn, session_id):
    """Get all measurements for a session."""
    rows = conn.execute("""
        SELECT * FROM mediciones WHERE sesion_id = ? ORDER BY id ASC
    """, (session_id,)).fetchall()
    return [dict(r) for r in rows]


def get_all_sessions(conn):
    """Get all sessions ordered by date."""
    rows = conn.execute(
        "SELECT * FROM sesiones ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_measurement(conn, session_id):
    """Get the most recent measurement for a session."""
    row = conn.execute("""
        SELECT * FROM mediciones WHERE sesion_id = ? ORDER BY id DESC LIMIT 1
    """, (session_id,)).fetchone()
    return dict(row) if row else None
