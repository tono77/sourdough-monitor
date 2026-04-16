"""Repositories — all SQL queries live here.

Every other module works with domain models (Session, Measurement).
Raw sqlite3 access is confined to this file.
"""

import logging
import sqlite3
from datetime import date, datetime
from typing import Optional

from sourdough.models import CalibrationBounds, Measurement, Session

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SessionRepository
# ---------------------------------------------------------------------------

class SessionRepository:
    """CRUD operations for fermentation sessions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # -- Queries ------------------------------------------------------------

    def get_by_id(self, session_id: int) -> Optional[Session]:
        row = self._conn.execute(
            "SELECT * FROM sesiones WHERE id = ?", (session_id,)
        ).fetchone()
        return Session.from_row(dict(row)) if row else None

    def get_active_today(self) -> Optional[Session]:
        today = date.today().isoformat()
        row = self._conn.execute(
            "SELECT * FROM sesiones WHERE fecha = ? AND estado = 'activa'",
            (today,),
        ).fetchone()
        return Session.from_row(dict(row)) if row else None

    def get_all(self) -> list[Session]:
        rows = self._conn.execute(
            "SELECT * FROM sesiones ORDER BY id DESC"
        ).fetchall()
        return [Session.from_row(dict(r)) for r in rows]

    # -- Mutations ----------------------------------------------------------

    def create(self, inherit_calibration: bool = True) -> Session:
        """Create a new session for today, optionally inheriting calibration."""
        today = date.today().isoformat()
        now = datetime.now().isoformat()

        if inherit_calibration:
            prev = self._conn.execute(
                "SELECT is_calibrated, fondo_y_pct, tope_y_pct, base_y_pct, "
                "izq_x_pct, der_x_pct FROM sesiones ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if prev and prev[0] == 1:
                cursor = self._conn.execute(
                    "INSERT INTO sesiones "
                    "(fecha, hora_inicio, estado, is_calibrated, "
                    " fondo_y_pct, tope_y_pct, base_y_pct, izq_x_pct, der_x_pct) "
                    "VALUES (?, ?, 'activa', ?, ?, ?, ?, ?, ?)",
                    (today, now, prev[0], prev[1], prev[2], prev[3], prev[4], prev[5]),
                )
                self._conn.commit()
                log.info("New session #%d created (inherited calibration)", cursor.lastrowid)
                return self.get_by_id(cursor.lastrowid)  # type: ignore[return-value]

        cursor = self._conn.execute(
            "INSERT INTO sesiones (fecha, hora_inicio, estado) VALUES (?, ?, 'activa')",
            (today, now),
        )
        self._conn.commit()
        log.info("New session #%d created for %s", cursor.lastrowid, today)
        return self.get_by_id(cursor.lastrowid)  # type: ignore[return-value]

    def get_or_create_today(self) -> Session:
        """Return today's active session or create a new one."""
        session = self.get_active_today()
        if session:
            return session
        return self.create()

    def close(self, session_id: int) -> None:
        """Close a session, recording stats and peak."""
        now = datetime.now().isoformat()
        count = self._conn.execute(
            "SELECT COUNT(*) FROM mediciones WHERE sesion_id = ?", (session_id,)
        ).fetchone()[0]

        peak_row = self._conn.execute(
            "SELECT nivel_pct, timestamp FROM mediciones "
            "WHERE sesion_id = ? AND nivel_pct IS NOT NULL "
            "ORDER BY nivel_pct DESC LIMIT 1",
            (session_id,),
        ).fetchone()

        peak_nivel = peak_row[0] if peak_row else None
        peak_ts = peak_row[1] if peak_row else None

        self._conn.execute(
            "UPDATE sesiones SET hora_fin = ?, estado = 'completada', "
            "num_mediciones = ?, peak_nivel = ?, peak_timestamp = ? "
            "WHERE id = ?",
            (now, count, peak_nivel, peak_ts, session_id),
        )
        self._conn.commit()
        log.info("Session #%d closed with %d measurements", session_id, count)

    def update_calibration(self, session_id: int, calib: CalibrationBounds) -> None:
        """Write calibration bounds to a session."""
        self._conn.execute(
            "UPDATE sesiones SET fondo_y_pct = ?, tope_y_pct = ?, base_y_pct = ?, "
            "izq_x_pct = ?, der_x_pct = ?, is_calibrated = 1 WHERE id = ?",
            (calib.fondo_y_pct, calib.tope_y_pct, calib.base_y_pct,
             calib.izq_x_pct, calib.der_x_pct, session_id),
        )
        self._conn.commit()

    def update_timelapse(self, session_id: int, url: str, file_id: str) -> None:
        self._conn.execute(
            "UPDATE sesiones SET timelapse_url = ?, timelapse_file_id = ? WHERE id = ?",
            (url, file_id, session_id),
        )
        self._conn.commit()

    def to_dict(self, session: Session) -> dict:
        """Serialize for Firestore sync."""
        return {
            "id": session.id,
            "fecha": session.fecha,
            "hora_inicio": session.hora_inicio,
            "hora_fin": session.hora_fin,
            "estado": session.estado,
            "num_mediciones": session.num_mediciones,
            "peak_nivel": session.peak_nivel,
            "peak_timestamp": session.peak_timestamp,
            "notas": session.notas,
            "fondo_y_pct": session.calibration.fondo_y_pct,
            "tope_y_pct": session.calibration.tope_y_pct,
            "base_y_pct": session.calibration.base_y_pct,
            "izq_x_pct": session.calibration.izq_x_pct,
            "der_x_pct": session.calibration.der_x_pct,
            "is_calibrated": int(session.is_calibrated),
            "timelapse_url": session.timelapse_url,
            "timelapse_file_id": session.timelapse_file_id,
        }


# ---------------------------------------------------------------------------
# MeasurementRepository
# ---------------------------------------------------------------------------

class MeasurementRepository:
    """CRUD operations for fermentation measurements."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # -- Queries ------------------------------------------------------------

    def get_by_session(self, session_id: int) -> list[Measurement]:
        rows = self._conn.execute(
            "SELECT * FROM mediciones WHERE sesion_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [Measurement.from_row(dict(r)) for r in rows]

    def get_latest(self, session_id: int) -> Optional[Measurement]:
        row = self._conn.execute(
            "SELECT * FROM mediciones WHERE sesion_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return Measurement.from_row(dict(row)) if row else None

    def get_baseline_nivel(self, session_id: int) -> Optional[float]:
        row = self._conn.execute(
            "SELECT nivel_pct FROM mediciones "
            "WHERE sesion_id = ? AND nivel_pct IS NOT NULL "
            "ORDER BY id ASC LIMIT 1",
            (session_id,),
        ).fetchone()
        return float(row[0]) if row else None

    def get_baseline_altura(self, session_id: int, after_timestamp: str | None = None) -> Optional[float]:
        """Get the first measurement's fused surface position for growth calculation.

        If after_timestamp is provided, returns the first measurement after that
        timestamp (used for cycle-aware baseline after a refresh).
        """
        if after_timestamp:
            row = self._conn.execute(
                "SELECT altura_pct FROM mediciones "
                "WHERE sesion_id = ? AND altura_pct IS NOT NULL AND timestamp > ? "
                "ORDER BY id ASC LIMIT 1",
                (session_id, after_timestamp),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT altura_pct FROM mediciones "
                "WHERE sesion_id = ? AND altura_pct IS NOT NULL "
                "ORDER BY id ASC LIMIT 1",
                (session_id,),
            ).fetchone()
        return float(row[0]) if row else None

    def get_baseline_foto(self, session_id: int, after_timestamp: str | None = None) -> Optional[str]:
        if after_timestamp:
            row = self._conn.execute(
                "SELECT foto_path FROM mediciones "
                "WHERE sesion_id = ? AND foto_path IS NOT NULL AND timestamp > ? "
                "ORDER BY id ASC LIMIT 1",
                (session_id, after_timestamp),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT foto_path FROM mediciones "
                "WHERE sesion_id = ? AND foto_path IS NOT NULL "
                "ORDER BY id ASC LIMIT 1",
                (session_id,),
            ).fetchone()
        return row[0] if row else None

    def get_first_timestamp(self, session_id: int) -> Optional[str]:
        row = self._conn.execute(
            "SELECT MIN(timestamp) FROM mediciones WHERE sesion_id = ?",
            (session_id,),
        ).fetchone()
        return row[0] if row else None

    def get_chart_data(self, session_id: int) -> list[sqlite3.Row]:
        """Return rows needed for chart generation (timestamp, nivel_pct, burbujas, textura, es_peak)."""
        return self._conn.execute(
            "SELECT timestamp, nivel_pct, burbujas, textura, es_peak "
            "FROM mediciones "
            "WHERE sesion_id = ? AND nivel_pct IS NOT NULL "
            "ORDER BY id ASC",
            (session_id,),
        ).fetchall()

    # -- Mutations ----------------------------------------------------------

    def save(self, session_id: int, foto_path: str, merged: dict) -> Measurement:
        """Save a pre-computed measurement from measurement.py fusion service."""
        timestamp = datetime.now().isoformat()

        self._conn.execute(
            "INSERT INTO mediciones "
            "(sesion_id, timestamp, foto_path, nivel_pct, "
            " burbujas, textura, notas, confianza, modo_analisis, "
            " altura_y_pct, altura_pct, crecimiento_pct, fuente) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                timestamp,
                str(foto_path),
                merged.get("nivel_pct"),
                merged.get("burbujas"),
                merged.get("textura"),
                merged.get("notas"),
                merged.get("confianza"),
                merged.get("fuente"),
                merged.get("altura_y_pct"),
                merged.get("altura_pct"),
                merged.get("crecimiento_pct"),
                merged.get("fuente"),
            ),
        )
        self._conn.execute(
            "UPDATE sesiones SET num_mediciones = num_mediciones + 1 WHERE id = ?",
            (session_id,),
        )
        self._conn.commit()

        return Measurement(
            sesion_id=session_id,
            timestamp=timestamp,
            foto_path=str(foto_path),
            nivel_pct=merged.get("nivel_pct"),
            burbujas=merged.get("burbujas", ""),
            textura=merged.get("textura", ""),
            notas=merged.get("notas", ""),
            confianza=merged.get("confianza"),
            modo_analisis=merged.get("fuente"),
            altura_y_pct=merged.get("altura_y_pct"),
            altura_pct=merged.get("altura_pct"),
            crecimiento_pct=merged.get("crecimiento_pct"),
            fuente=merged.get("fuente"),
        )

    def apply_corrections(self, session_id: int, corrections: list[dict]) -> int:
        """Apply manual corrections from Firestore to local DB labels.

        Matches corrections to measurements by timestamp and updates
        altura_pct so the ML model can learn from ground truth.

        Returns the number of measurements updated.
        """
        updated = 0
        for corr in corrections:
            ts = corr.get("timestamp")
            nivel = corr.get("nivel_pct")
            if not ts or nivel is None:
                continue

            # Match by timestamp prefix (Firestore IDs replace : with -)
            ts_clean = ts.replace("-", ":").replace(".", ":")
            row = self._conn.execute(
                "SELECT id, altura_pct FROM mediciones "
                "WHERE sesion_id = ? AND timestamp LIKE ?",
                (session_id, ts_clean[:16] + "%"),
            ).fetchone()

            if row:
                # If correction has altura_y_pct, use that directly as ground truth
                altura = corr.get("altura_y_pct") or corr.get("altura_pct")
                if altura is not None:
                    self._conn.execute(
                        "UPDATE mediciones SET altura_pct = ?, nivel_pct = ?, "
                        "fuente = 'manual' WHERE id = ?",
                        (float(altura), float(nivel), row[0]),
                    )
                    updated += 1

        if updated:
            self._conn.commit()
        return updated

    def mark_peak(self, session_id: int, measurement_id: int,
                  nivel: float, timestamp: str) -> None:
        """Flag a measurement as the session peak."""
        self._conn.execute(
            "UPDATE mediciones SET es_peak = 1 WHERE id = ?", (measurement_id,)
        )
        self._conn.execute(
            "UPDATE sesiones SET peak_nivel = ?, peak_timestamp = ? WHERE id = ?",
            (nivel, timestamp, session_id),
        )
        self._conn.commit()

    def peak_exists(self, session_id: int) -> bool:
        count = self._conn.execute(
            "SELECT COUNT(*) FROM mediciones WHERE sesion_id = ? AND es_peak = 1",
            (session_id,),
        ).fetchone()[0]
        return count > 0

    def get_max_nivel(self, session_id: int) -> Optional[float]:
        row = self._conn.execute(
            "SELECT MAX(nivel_pct) FROM mediciones "
            "WHERE sesion_id = ? AND nivel_pct IS NOT NULL",
            (session_id,),
        ).fetchone()
        return row[0] if row and row[0] is not None else None

    def get_peak_candidate(self, session_id: int) -> Optional[dict]:
        """Return the measurement with the highest nivel_pct for peak marking."""
        row = self._conn.execute(
            "SELECT id, nivel_pct, timestamp FROM mediciones "
            "WHERE sesion_id = ? AND nivel_pct IS NOT NULL "
            "ORDER BY nivel_pct DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return {"id": row[0], "nivel": row[1], "timestamp": row[2]}
        return None

    def get_recent(self, session_id: int, limit: int = 5) -> list[Measurement]:
        """Get the N most recent measurements (newest first)."""
        rows = self._conn.execute(
            "SELECT * FROM mediciones "
            "WHERE sesion_id = ? AND nivel_pct IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [Measurement.from_row(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Historical data migration
# ---------------------------------------------------------------------------

def migrate_historical_data(conn: sqlite3.Connection) -> None:
    """Migrate old measurements without sesion_id into a historical session."""
    orphans = conn.execute(
        "SELECT COUNT(*) FROM mediciones WHERE sesion_id IS NULL"
    ).fetchone()[0]

    if orphans == 0:
        return

    first = conn.execute(
        "SELECT timestamp FROM mediciones WHERE sesion_id IS NULL ORDER BY id ASC LIMIT 1"
    ).fetchone()
    last = conn.execute(
        "SELECT timestamp FROM mediciones WHERE sesion_id IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if first and last:
        fecha = first[0][:10]
        cursor = conn.execute(
            "INSERT INTO sesiones (fecha, hora_inicio, hora_fin, estado, notas) "
            "VALUES (?, ?, ?, 'completada', 'Sesión histórica migrada')",
            (fecha, first[0], last[0]),
        )
        session_id = cursor.lastrowid
        conn.execute(
            "UPDATE mediciones SET sesion_id = ? WHERE sesion_id IS NULL",
            (session_id,),
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM mediciones WHERE sesion_id = ?", (session_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE sesiones SET num_mediciones = ? WHERE id = ?",
            (count, session_id),
        )
        conn.commit()
        log.info("Migrated %d historical measurements into session #%d", orphans, session_id)
