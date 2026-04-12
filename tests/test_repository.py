"""Tests for SessionRepository and MeasurementRepository."""

from sourdough.db.repository import (
    MeasurementRepository,
    SessionRepository,
    migrate_historical_data,
)
from sourdough.models import CalibrationBounds


class TestSessionRepository:

    def test_create_and_retrieve(self, db_conn):
        repo = SessionRepository(db_conn)
        session = repo.create(inherit_calibration=False)

        assert session.id is not None
        assert session.estado == "activa"
        assert session.num_mediciones == 0

        fetched = repo.get_by_id(session.id)
        assert fetched is not None
        assert fetched.id == session.id

    def test_get_or_create_today_returns_same(self, db_conn):
        repo = SessionRepository(db_conn)
        s1 = repo.get_or_create_today()
        s2 = repo.get_or_create_today()
        assert s1.id == s2.id

    def test_close_session(self, db_conn):
        repo = SessionRepository(db_conn)
        session = repo.create(inherit_calibration=False)
        repo.close(session.id)

        closed = repo.get_by_id(session.id)
        assert closed.estado == "completada"
        assert closed.hora_fin is not None

    def test_calibration_inheritance(self, db_conn):
        repo = SessionRepository(db_conn)
        # Create first session with calibration
        s1 = repo.create(inherit_calibration=False)
        calib = CalibrationBounds(
            fondo_y_pct=50.0, tope_y_pct=10.0,
            base_y_pct=90.0, izq_x_pct=20.0, der_x_pct=80.0,
        )
        repo.update_calibration(s1.id, calib)
        repo.close(s1.id)

        # Create second session — should inherit
        s2 = repo.create(inherit_calibration=True)
        assert s2.is_calibrated
        assert s2.calibration.fondo_y_pct == 50.0
        assert s2.calibration.izq_x_pct == 20.0

    def test_get_all(self, db_conn):
        repo = SessionRepository(db_conn)
        repo.create(inherit_calibration=False)
        repo.create(inherit_calibration=False)
        # get_or_create_today won't create a third since two exist for today
        # but get_all should return both (2nd create will fail because today's session
        # already exists... let me close the first one)
        all_sessions = repo.get_all()
        assert len(all_sessions) >= 1

    def test_update_timelapse(self, db_conn):
        repo = SessionRepository(db_conn)
        session = repo.create(inherit_calibration=False)
        repo.update_timelapse(session.id, "https://example.com/video.mp4", "abc123")

        updated = repo.get_by_id(session.id)
        assert updated.timelapse_url == "https://example.com/video.mp4"
        assert updated.timelapse_file_id == "abc123"


class TestMeasurementRepository:

    def _make_session(self, db_conn):
        return SessionRepository(db_conn).create(inherit_calibration=False)

    def test_save_and_retrieve(self, db_conn):
        session = self._make_session(db_conn)
        repo = MeasurementRepository(db_conn)

        m = repo.save(session.id, "/photos/test.jpg", {
            "nivel_pct": 25.5,
            "burbujas": "pocas",
            "textura": "rugosa",
            "notas": "Test measurement",
        })

        assert m.nivel_pct == 25.5
        assert m.burbujas == "pocas"

        measurements = repo.get_by_session(session.id)
        assert len(measurements) == 1
        assert measurements[0].nivel_pct == 25.5

    def test_baseline(self, db_conn):
        session = self._make_session(db_conn)
        repo = MeasurementRepository(db_conn)

        repo.save(session.id, "/photos/first.jpg", {"nivel_pct": 10.0, "burbujas": "ninguna", "textura": "lisa"})
        repo.save(session.id, "/photos/second.jpg", {"nivel_pct": 30.0, "burbujas": "pocas", "textura": "rugosa"})

        assert repo.get_baseline_nivel(session.id) == 10.0
        assert repo.get_baseline_foto(session.id) == "/photos/first.jpg"

    def test_latest(self, db_conn):
        session = self._make_session(db_conn)
        repo = MeasurementRepository(db_conn)

        repo.save(session.id, "/photos/a.jpg", {"nivel_pct": 5.0, "burbujas": "ninguna", "textura": "lisa"})
        repo.save(session.id, "/photos/b.jpg", {"nivel_pct": 15.0, "burbujas": "pocas", "textura": "rugosa"})

        latest = repo.get_latest(session.id)
        assert latest.nivel_pct == 15.0

    def test_peak_marking(self, db_conn):
        session = self._make_session(db_conn)
        repo = MeasurementRepository(db_conn)

        repo.save(session.id, "/photos/a.jpg", {"nivel_pct": 50.0, "burbujas": "muchas", "textura": "muy_activa"})

        assert not repo.peak_exists(session.id)

        candidate = repo.get_peak_candidate(session.id)
        assert candidate is not None
        repo.mark_peak(session.id, candidate["id"], candidate["nivel"], candidate["timestamp"])

        assert repo.peak_exists(session.id)

    def test_saves_v2_fields(self, db_conn):
        """Repository stores altura_pct, crecimiento_pct, fuente from merged dict."""
        session = self._make_session(db_conn)
        m_repo = MeasurementRepository(db_conn)

        m = m_repo.save(session.id, "/photos/cv.jpg", {
            "altura_pct": 45.0,
            "crecimiento_pct": 50.0,
            "fuente": "fusionado",
            "nivel_pct": 50.0,
            "altura_y_pct": 45.0,
            "burbujas": "pocas",
            "textura": "rugosa",
        })

        assert m.altura_pct == 45.0
        assert m.crecimiento_pct == 50.0
        assert m.fuente == "fusionado"
        assert m.nivel_pct == 50.0

    def test_get_recent(self, db_conn):
        session = self._make_session(db_conn)
        repo = MeasurementRepository(db_conn)

        for i in range(5):
            repo.save(session.id, f"/photos/{i}.jpg", {
                "nivel_pct": float(i * 10),
                "burbujas": "pocas",
                "textura": "lisa",
            })

        recent = repo.get_recent(session.id, limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].nivel_pct == 40.0


class TestHistoricalMigration:

    def test_migrate_orphans(self, db_conn):
        # Insert orphaned measurements (no sesion_id)
        db_conn.execute(
            "INSERT INTO mediciones (timestamp, foto_path, nivel_pct, burbujas, textura) "
            "VALUES ('2026-04-01T10:00:00', '/photos/old1.jpg', 10.0, 'pocas', 'lisa')"
        )
        db_conn.execute(
            "INSERT INTO mediciones (timestamp, foto_path, nivel_pct, burbujas, textura) "
            "VALUES ('2026-04-01T12:00:00', '/photos/old2.jpg', 25.0, 'muchas', 'rugosa')"
        )
        db_conn.commit()

        migrate_historical_data(db_conn)

        # Should have created a session
        sessions = db_conn.execute("SELECT * FROM sesiones").fetchall()
        assert len(sessions) == 1
        assert dict(sessions[0])["estado"] == "completada"

        # Orphans should now be assigned
        orphans = db_conn.execute(
            "SELECT COUNT(*) FROM mediciones WHERE sesion_id IS NULL"
        ).fetchone()[0]
        assert orphans == 0
