#!/usr/bin/env python3
"""Local HTTP server for the manual labeling UI.

Serves index.html, the photos referenced in samples_to_label.json, and
persists each label append-only to manual_labels.json so nothing is lost
if the browser crashes mid-session.

Usage:
    python scripts/labeling/server.py [--port 8765]
    open http://localhost:8765
"""

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for _ in range(10):
        if (p / "data" / "fermento.db").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    sys.exit("Could not locate data/fermento.db walking up from the script.")


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = find_repo_root(SCRIPT_DIR)
SAMPLES_PATH = ROOT / "data" / "ml_dataset" / "samples_to_label.json"
LABELS_PATH = ROOT / "data" / "ml_dataset" / "manual_labels.json"

_write_lock = threading.Lock()


def load_samples() -> list[dict]:
    if not SAMPLES_PATH.exists():
        sys.exit(f"Run select_samples.py first — {SAMPLES_PATH} not found.")
    with open(SAMPLES_PATH) as f:
        return json.load(f)


def load_labels() -> dict[int, dict]:
    """Return {measurement_id: label_dict} for already-labeled samples."""
    if not LABELS_PATH.exists():
        return {}
    with open(LABELS_PATH) as f:
        data = json.load(f)
    return {int(entry["id"]): entry for entry in data}


def append_label(label: dict) -> None:
    """Append (or replace) a label entry to manual_labels.json atomically."""
    with _write_lock:
        existing = []
        if LABELS_PATH.exists():
            with open(LABELS_PATH) as f:
                existing = json.load(f)
        # Drop any previous entry for the same id so re-labels overwrite
        mid = int(label["id"])
        existing = [e for e in existing if int(e["id"]) != mid]
        existing.append(label)

        tmp = LABELS_PATH.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, LABELS_PATH)


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_error(404, f"Not found: {path}")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/" or path == "/index.html":
            self._send_file(SCRIPT_DIR / "index.html", "text/html; charset=utf-8")
            return

        if path == "/api/samples":
            samples = load_samples()
            labels = load_labels()
            for s in samples:
                lbl = labels.get(int(s["id"]))
                s["labeled"] = lbl is not None
                if lbl:
                    s["label"] = lbl
            self._send_json(samples)
            return

        if path == "/api/image":
            qs = parse_qs(url.query)
            mid = qs.get("id", [""])[0]
            if not mid.isdigit():
                self.send_error(400, "id required")
                return
            samples = load_samples()
            match = next((s for s in samples if int(s["id"]) == int(mid)), None)
            if not match:
                self.send_error(404, "sample not found")
                return
            photo_path = Path(match["foto_path"])
            if not photo_path.exists():
                self.send_error(404, f"photo missing: {photo_path}")
                return
            ctype = "image/jpeg" if photo_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            self._send_file(photo_path, ctype)
            return

        self.send_error(404, "unknown route")

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/api/label":
            self.send_error(404, "unknown route")
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_error(400, "invalid JSON")
            return

        required = ["id", "tope_y_pct", "base_y_pct", "izq_x_pct", "der_x_pct",
                    "surface_y_pct", "altura_pct"]
        missing = [k for k in required if k not in payload]
        if missing:
            self.send_error(400, f"missing fields: {missing}")
            return

        append_label(payload)
        self._send_json({"ok": True, "id": payload["id"]})

    def log_message(self, fmt, *args):
        # Quieter default logging
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    samples = load_samples()
    labels = load_labels()
    print(f"Samples:  {len(samples)}")
    print(f"Labeled:  {len(labels)}  (pending: {len(samples) - len(labels)})")
    print(f"Labels:   {LABELS_PATH}")
    print(f"\nOpen: http://{args.host}:{args.port}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye.")
        server.shutdown()


if __name__ == "__main__":
    main()
