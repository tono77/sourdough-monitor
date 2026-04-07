#!/usr/bin/env python3
"""
Sourdough Monitor — Dashboard Web Server
Serves the real-time dashboard and API endpoints.
"""

import json
import os
import http.server
import urllib.parse
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"
PHOTOS_DIR = BASE_DIR / "photos"
CHARTS_DIR = BASE_DIR / "charts"


def get_db_connection():
    """Get a read-only database connection."""
    from db import get_connection
    return get_connection()


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for dashboard and API."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def send_json(self, data, status=200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def send_file(self, filepath, content_type):
        """Send a file."""
        if not filepath.exists():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Dashboard HTML
        if path == "/" or path == "/index.html":
            self.send_file(DASHBOARD_DIR / "index.html", "text/html; charset=utf-8")
            return

        # API endpoints
        if path.startswith("/api/"):
            self.handle_api(path, parsed.query)
            return

        # Serve photos
        if path.startswith("/photos/"):
            filename = path[8:]  # Remove /photos/
            # Security: prevent directory traversal
            if ".." in filename or "/" in filename:
                self.send_error(403)
                return
            photo_path = PHOTOS_DIR / filename
            ext = photo_path.suffix.lower()
            ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
            self.send_file(photo_path, ct)
            return

        # Serve charts
        if path.startswith("/charts/"):
            filename = path[8:]
            if ".." in filename or "/" in filename:
                self.send_error(403)
                return
            self.send_file(CHARTS_DIR / filename, "image/png")
            return

        self.send_error(404)

    def handle_api(self, path, query):
        """Handle API requests."""
        try:
            conn = get_db_connection()

            if path == "/api/sessions":
                rows = conn.execute(
                    "SELECT * FROM sesiones ORDER BY id DESC"
                ).fetchall()
                self.send_json([dict(r) for r in rows])

            elif path == "/api/sessions/active":
                row = conn.execute(
                    "SELECT * FROM sesiones WHERE estado = 'activa' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    session = dict(row)
                    # Include recent measurements
                    measurements = conn.execute("""
                        SELECT * FROM mediciones WHERE sesion_id = ? ORDER BY id ASC
                    """, (session["id"],)).fetchall()
                    session["measurements"] = [dict(m) for m in measurements]

                    # Latest measurement
                    latest = conn.execute("""
                        SELECT * FROM mediciones WHERE sesion_id = ? ORDER BY id DESC LIMIT 1
                    """, (session["id"],)).fetchone()
                    session["latest"] = dict(latest) if latest else None

                    self.send_json(session)
                else:
                    self.send_json(None)

            elif path.startswith("/api/sessions/"):
                session_id = path.split("/")[-1]
                if session_id.isdigit():
                    row = conn.execute(
                        "SELECT * FROM sesiones WHERE id = ?", (int(session_id),)
                    ).fetchone()
                    if row:
                        session = dict(row)
                        measurements = conn.execute("""
                            SELECT * FROM mediciones WHERE sesion_id = ? ORDER BY id ASC
                        """, (session["id"],)).fetchall()
                        session["measurements"] = [dict(m) for m in measurements]
                        self.send_json(session)
                    else:
                        self.send_json(None, 404)
                else:
                    self.send_json({"error": "Invalid session ID"}, 400)

            elif path == "/api/photos":
                # List available photos
                photos = []
                if PHOTOS_DIR.exists():
                    for f in sorted(PHOTOS_DIR.glob("fermento_*.jpg"), reverse=True)[:50]:
                        photos.append({
                            "name": f.name,
                            "size": f.stat().st_size,
                            "url": f"/photos/{f.name}"
                        })
                self.send_json(photos)

            elif path == "/api/charts":
                # List available charts
                charts = []
                if CHARTS_DIR.exists():
                    for f in sorted(CHARTS_DIR.glob("sourdough_*.png"), reverse=True)[:20]:
                        charts.append({
                            "name": f.name,
                            "url": f"/charts/{f.name}"
                        })
                self.send_json(charts)

            elif path == "/api/status":
                # General system status
                total_sessions = conn.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0]
                total_measurements = conn.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]
                active = conn.execute(
                    "SELECT * FROM sesiones WHERE estado = 'activa' ORDER BY id DESC LIMIT 1"
                ).fetchone()

                self.send_json({
                    "total_sessions": total_sessions,
                    "total_measurements": total_measurements,
                    "active_session": dict(active) if active else None,
                    "server_time": datetime.now().isoformat(),
                    "photos_count": len(list(PHOTOS_DIR.glob("fermento_*.jpg"))) if PHOTOS_DIR.exists() else 0,
                })

            else:
                self.send_json({"error": "Unknown endpoint"}, 404)

            conn.close()

        except Exception as e:
            self.send_json({"error": str(e)}, 500)


def run_server(host="0.0.0.0", port=8080):
    """Start the dashboard web server."""
    server = http.server.HTTPServer((host, port), DashboardHandler)
    server.serve_forever()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"🌐 Dashboard server on http://localhost:{port}")
    run_server(port=port)
